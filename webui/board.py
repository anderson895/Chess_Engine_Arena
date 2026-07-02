# ═══════════════════════════════════════════════════════════
#  webui/board.py — Chess board component and eval bar
#
#  The board is a CSS grid of 64 divs. Squares are created once;
#  refresh() only swaps classes and piece glyphs, so updates are
#  cheap and every element is inspectable in browser DevTools.
# ═══════════════════════════════════════════════════════════

import math

from nicegui import ui

from webui.theme import piece_src


def piece_url(pc):
    """Sprite URL for a board piece letter, honoring the active design."""
    return piece_src(("w" if pc.isupper() else "b") + pc.upper())


def uci_to_squares(uci):
    """Return ((from_r, from_c), (to_r, to_c)) for a UCI move, or (None, None)."""
    if not uci or len(uci) < 4:
        return None, None
    try:
        return ((8 - int(uci[1]), ord(uci[0]) - ord("a")),
                (8 - int(uci[3]), ord(uci[2]) - ord("a")))
    except (ValueError, IndexError):
        return None, None


class BoardView:
    """
    Renders a chess position as an 8×8 CSS grid.

    Parameters
    ----------
    state_provider : callable → dict with keys:
        board       — core.board.Board instance
        last_move   — UCI string or None
        selected    — (r, c) or None
        legal_dests — set of (r, c)
        check_sq    — (r, c) or None
    on_click : async callable(br, bc) | None
        Invoked with *board* coordinates when a square is clicked.
    """

    def __init__(self, state_provider, on_click=None):
        self._state = state_provider
        self._on_click = on_click
        self.flipped = False
        self._squares = []          # 64 dicts in display order

        with ui.element("div").classes("board-grid") as grid:
            self.grid = grid
            for row in range(8):
                for col in range(8):
                    light = (row + col) % 2 == 0
                    sq = ui.element("div").classes(
                        f"board-sq {'light' if light else 'dark'}")
                    with sq:
                        piece = ui.element("img").classes("pc-img")
                        piece.set_visibility(False)
                        rank_lbl = file_lbl = None
                        if col == 0:
                            rank_lbl = ui.label("").classes("coord rank")
                        if row == 7:
                            file_lbl = ui.label("").classes("coord file")
                    if self._on_click:
                        sq.on("click", self._make_click_handler(row, col))
                    self._squares.append({
                        "el": sq, "piece": piece, "light": light,
                        "rank": rank_lbl, "file": file_lbl,
                    })
        self.refresh()

    # ── Interaction ───────────────────────────────────────

    def _make_click_handler(self, row, col):
        async def handler():
            br = 7 - row if self.flipped else row
            bc = 7 - col if self.flipped else col
            await self._on_click(br, bc)
        return handler

    def flip(self):
        self.flipped = not self.flipped
        self.refresh()

    def redraw_pieces(self):
        """Re-apply every piece sprite (the piece design changed)."""
        for cell in self._squares:
            if cell.get("pc"):
                cell["piece"].props(f'src="{piece_url(cell["pc"])}"')

    # ── Rendering ─────────────────────────────────────────

    def refresh(self):
        """
        Re-render the position. Every square caches its last classes and
        piece so only *changed* squares emit updates — a normal move
        touches ~4 elements instead of 64, keeping the websocket quiet.
        """
        state = self._state()
        board       = state["board"]
        selected    = state.get("selected")
        legal_dests = state.get("legal_dests") or set()
        check_sq    = state.get("check_sq")
        lm_from, lm_to = uci_to_squares(state.get("last_move"))

        update_coords = getattr(self, "_coord_flip", None) != self.flipped
        self._coord_flip = self.flipped

        for row in range(8):
            for col in range(8):
                cell = self._squares[row * 8 + col]
                br = 7 - row if self.flipped else row
                bc = 7 - col if self.flipped else col

                classes = ["board-sq", "light" if cell["light"] else "dark"]
                if selected and (br, bc) == selected:
                    classes.append("sel")
                elif lm_from and (br, bc) == lm_from:
                    classes.append("lfrom")
                elif lm_to and (br, bc) == lm_to:
                    classes.append("lto")
                if check_sq and (br, bc) == check_sq:
                    classes.append("chk")

                pc = board.get(br, bc)
                has_piece = pc and pc != "."
                if (br, bc) in legal_dests:
                    classes.append("ring" if has_piece else "dot")

                cls = " ".join(classes)
                if cell.get("cls") != cls:
                    cell["el"].classes(replace=cls)
                    cell["cls"] = cls

                new_pc = pc if has_piece else None
                if cell.get("pc") != new_pc:
                    if new_pc:
                        cell["piece"].props(f'src="{piece_url(new_pc)}"')
                        cell["piece"].set_visibility(True)
                    else:
                        cell["piece"].set_visibility(False)
                    cell["pc"] = new_pc

                if update_coords:
                    if cell["rank"] is not None:
                        cell["rank"].set_text(str(8 - br))
                    if cell["file"] is not None:
                        cell["file"].set_text(chr(ord("a") + bc))


class EvalBar:
    """Vertical evaluation bar (White's share fills from the bottom)."""

    def __init__(self):
        with ui.element("div").classes("eval-bar flex-grow") as root:
            self.root = root
            self.white_part = ui.element("div").classes("white-part")
            ui.element("div").classes("mid")
            self.val = ui.label("0.0").classes("val").style(
                "top: 2px; color: #EEE; text-shadow: 0 1px 2px #000;")
        self.set_cp(0)

    def set_cp(self, cp):
        cp = max(-1000, min(1000, cp if cp is not None else 0))
        if getattr(self, "_last_cp", None) == cp:
            return   # no change → no client update
        self._last_cp = cp
        ratio = 0.5 + 0.5 * math.tanh(cp / 400.0)
        self.white_part.style(f"height: {ratio * 100:.1f}%")
        if abs(cp) >= 1000:
            txt = "M" if cp > 0 else "-M"
        else:
            txt = f"{cp / 100:+.1f}"
        self.val.set_text(txt)
        if cp >= 0:
            # White ahead → show value in the black (top) area
            self.val.style("top: 2px; bottom: auto; color: #EEE;")
        else:
            self.val.style("top: auto; bottom: 2px; color: #222;")
