# ═══════════════════════════════════════════════════════════
#  webui/board.py — Chess board component and eval bar
#
#  The board is a CSS grid of 64 divs. Squares are created once;
#  refresh() only swaps classes and piece glyphs, so updates are
#  cheap and every element is inspectable in browser DevTools.
# ═══════════════════════════════════════════════════════════

import math

from nicegui import ui

from core.board import parse_uci
from webui.quality import icon_body
from webui.theme import piece_src


def piece_url(pc):
    """Sprite URL for a board piece letter, honoring the active design."""
    return piece_src(("w" if pc.isupper() else "b") + pc.upper())


def uci_to_squares(uci):
    """Return ((from_r, from_c), (to_r, to_c)) for a UCI move, or (None, None)."""
    try:
        fr, fc, tr, tc, _ = parse_uci(uci)
    except ValueError:
        return None, None
    return (fr, fc), (tr, tc)


# Dragging a piece, run in the browser so the piece follows the pointer
# with no round trip. Python hears of a drag twice: "start" once the
# pointer has really moved (so the piece is picked up and its moves show),
# and "drop" with the square it was let go on. A press and release with no
# movement in between is left alone — it is an ordinary click. Squares are
# sent as display indexes 0..63; BoardView turns them into board squares.
_DRAG_JS = """(e) => {
  if (e.button !== 0) return;
  const grid = e.currentTarget;
  const sq = e.target.closest('.board-sq');
  if (!sq || sq.parentElement !== grid || !sq.classList.contains('can-drag')) return;
  const img = sq.querySelector('img.pc-img');
  if (!img) return;
  e.preventDefault();
  const squares = Array.from(grid.children).filter(el => el.classList.contains('board-sq'));
  const from = squares.indexOf(sq);
  const x0 = e.clientX, y0 = e.clientY;
  const size = img.getBoundingClientRect().width;
  let ghost = null, over = null;
  const follow = (ev) => {
    ghost.style.left = (ev.clientX - size / 2) + 'px';
    ghost.style.top = (ev.clientY - size / 2) + 'px';
    const hit = document.elementFromPoint(ev.clientX, ev.clientY);
    const t = hit && hit.closest('.board-sq');
    const target = t && t.parentElement === grid ? t : null;
    if (target !== over) {
      if (over) over.classList.remove('drag-over');
      over = target;
      if (over) over.classList.add('drag-over');
    }
  };
  const move = (ev) => {
    if (!ghost) {
      if (Math.hypot(ev.clientX - x0, ev.clientY - y0) < 4) return;
      ghost = document.createElement('img');
      ghost.src = img.src;
      ghost.className = 'drag-ghost';
      ghost.style.width = ghost.style.height = size + 'px';
      document.body.appendChild(ghost);
      img.style.visibility = 'hidden';
      emit({kind: 'start', from: from});
    }
    follow(ev);
  };
  const end = (ev) => {
    document.removeEventListener('pointermove', move);
    document.removeEventListener('pointerup', end);
    document.removeEventListener('pointercancel', end);
    if (!ghost) return;
    if (over) over.classList.remove('drag-over');
    // Letting go also counts as a click on the board: swallow it
    const swallow = (ce) => { ce.stopPropagation(); ce.preventDefault(); };
    grid.addEventListener('click', swallow, true);
    setTimeout(() => grid.removeEventListener('click', swallow, true), 0);
    const to = over ? squares.indexOf(over) : -1;
    const restore = () => { ghost.remove(); img.style.visibility = ''; };
    if (ev.type === 'pointerup' && to >= 0 && to !== from) {
      // Rest the piece on its new square until the board catches up;
      // an illegal move then snaps back
      const r = over.getBoundingClientRect();
      ghost.style.left = (r.left + (r.width - size) / 2) + 'px';
      ghost.style.top = (r.top + (r.height - size) / 2) + 'px';
      emit({kind: 'drop', from: from, to: to});
      setTimeout(restore, 300);
    } else {
      restore();
    }
  };
  document.addEventListener('pointermove', move);
  document.addEventListener('pointerup', end);
  document.addEventListener('pointercancel', end);
}"""


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
        movable     — set of (r, c) whose piece may be dragged (optional)
        premove     — UCI of a move queued for the player's turn, shown in
                      red until it is played (optional)
      and, for a board built with overlay=True:
        move_class  — classification of last_move ('Brilliant', …) or None;
                      tints its squares and puts its badge on the target
        arrows      — [(uci, colour)] arrows to draw, e.g. the best move
    on_click : async callable(br, bc) | None
        Invoked with *board* coordinates when a square is clicked.
    overlay : bool
        Add a layer above the pieces for move badges and arrows.
    on_drag_start : callable(br, bc) | None
        A piece on a *movable* square is being dragged: pick it up.
    on_drop : async callable(from_br, from_bc, to_br, to_bc) | None
        The dragged piece was let go on another square. Without it the
        pieces cannot be dragged, only clicked.
    on_right_click : callable() | None
        A right-click anywhere on the board, instead of the browser's menu.
    """

    def __init__(self, state_provider, on_click=None, overlay=False,
                 on_drag_start=None, on_drop=None, on_right_click=None):
        self._state = state_provider
        self._on_click = on_click
        self._on_drag_start = on_drag_start
        self._on_drop = on_drop
        self.flipped = False
        self._squares = []          # 64 dicts in display order
        self._overlay = None
        self._overlay_svg = None

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
            if overlay:
                # Our own SVG only — never anything typed or imported
                self._overlay = ui.html("", sanitize=False) \
                    .classes("board-overlay")
        if on_drop:
            grid.classes(add="draggable")
            grid.on("pointerdown", self._drag_event, js_handler=_DRAG_JS)
        if on_right_click:
            grid.on("contextmenu.prevent", lambda _e: on_right_click(), [])
        self.refresh()

    # ── Interaction ───────────────────────────────────────

    def _board_square(self, index):
        """Board (row, col) of the square shown at display *index* 0..63."""
        row, col = divmod(index, 8)
        return (7 - row, 7 - col) if self.flipped else (row, col)

    def _make_click_handler(self, row, col):
        async def handler():
            await self._on_click(*self._board_square(row * 8 + col))
        return handler

    async def _drag_event(self, e):
        """A drag reported by the browser: {kind: start|drop, from, to}."""
        args = e.args if isinstance(e.args, dict) else {}
        squares = []
        for key in ("from", "to"):
            index = args.get(key)
            squares.append(self._board_square(index)
                           if isinstance(index, int) and 0 <= index < 64 else None)
        src, dst = squares
        if src is None:
            return
        if args.get("kind") == "start":
            if self._on_drag_start:
                self._on_drag_start(*src)
        elif args.get("kind") == "drop" and dst is not None and dst != src:
            await self._on_drop(*src, *dst)

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
        movable     = (state.get("movable") or set()) if self._on_drop else set()
        move_class  = state.get("move_class")
        lm_from, lm_to = uci_to_squares(state.get("last_move"))
        premove     = set(uci_to_squares(state.get("premove"))) - {None}
        # A classified move is tinted in its class colour instead of the
        # usual last-move highlight
        lm_cls = (f"q-{move_class.lower()}", f"q-{move_class.lower()}") \
            if move_class else ("lfrom", "lto")

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
                elif (br, bc) in premove:
                    classes.append("pre")
                elif lm_from and (br, bc) == lm_from:
                    classes.append(lm_cls[0])
                elif lm_to and (br, bc) == lm_to:
                    classes.append(lm_cls[1])
                if check_sq and (br, bc) == check_sq:
                    classes.append("chk")
                if (br, bc) in movable:
                    classes.append("can-drag")

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

        if self._overlay is not None:
            svg = self._overlay_markup(state.get("arrows") or (),
                                       lm_to if move_class else None,
                                       move_class)
            if svg != self._overlay_svg:
                self._overlay.set_content(svg)
                self._overlay_svg = svg

    def _display(self, r, c):
        """Board square → (column, row) on screen, 0..7 from the top left."""
        return (7 - c, 7 - r) if self.flipped else (c, r)

    def _overlay_markup(self, arrows, badge_sq, badge_cls):
        """SVG for the arrows and the class badge, in square units."""
        parts = []
        for uci, color in arrows:
            frm, to = uci_to_squares(uci)
            if frm is None:
                continue
            x1, y1 = self._display(*frm)
            x2, y2 = self._display(*to)
            x1, y1, x2, y2 = x1 + .5, y1 + .5, x2 + .5, y2 + .5
            length = math.hypot(x2 - x1, y2 - y1)
            if length == 0:
                continue
            ux, uy = (x2 - x1) / length, (y2 - y1) / length
            head, half = 0.42, 0.24
            bx, by = x2 - ux * head, y2 - uy * head      # base of the head
            px, py = -uy, ux
            parts.append(
                f'<g opacity="0.82">'
                f'<line x1="{x1:.3f}" y1="{y1:.3f}" x2="{bx:.3f}" y2="{by:.3f}" '
                f'stroke="{color}" stroke-width="0.17" stroke-linecap="round"/>'
                f'<polygon fill="{color}" points="{x2:.3f},{y2:.3f} '
                f'{bx + px * half:.3f},{by + py * half:.3f} '
                f'{bx - px * half:.3f},{by - py * half:.3f}"/></g>')
        if badge_sq and badge_cls:
            col, row = self._display(*badge_sq)
            size = 0.44
            parts.append(
                f'<svg x="{col + 1 - size * 0.72:.3f}" y="{row - size * 0.28:.3f}" '
                f'width="{size}" height="{size}" viewBox="0 0 100 100">'
                f'{icon_body(badge_cls)}</svg>')
        if not parts:
            return ""
        return ('<svg viewBox="0 0 8 8" width="100%" height="100%" '
                'style="overflow: visible">' + "".join(parts) + "</svg>")


class EvalBar:
    """
    Vertical evaluation bar. White's share fills from the bottom — or from
    the top once flipped, so it always grows from White's side of the board.
    """

    def __init__(self):
        with ui.element("div").classes("eval-bar flex-grow") as root:
            self.root = root
            self.white_part = ui.element("div").classes("white-part")
            ui.element("div").classes("mid")
            self.val = ui.label("0.0").classes("val")
        self._flipped = False
        self._shown = None
        self.set_eval(0)

    def set_flipped(self, flipped):
        if flipped == self._flipped:
            return
        self._flipped = flipped
        if flipped:
            self.root.classes(add="flipped")
        else:
            self.root.classes(remove="flipped")
        shown, self._shown = self._shown, None
        if shown:
            self.set_eval(*shown)

    def set_cp(self, cp):
        """Centipawns from White's side; ±30000 is the old 'forced mate'."""
        if cp is not None and abs(cp) >= 30000:
            self.set_eval(None, 1 if cp > 0 else -1, mate_text="M")
        else:
            self.set_eval(cp)

    def set_eval(self, cp, mate=None, mate_text=None):
        """
        Show an evaluation from White's side: *cp* centipawns, or a forced
        mate in *mate* moves (negative when Black mates, 0 once it is mate).
        """
        if (cp, mate) == self._shown:
            return   # no change → no client update
        self._shown = (cp, mate)
        if mate is not None:
            white_ahead = mate > 0 or (mate == 0 and (cp or 0) >= 0)
            ratio = 1.0 if white_ahead else 0.0
            txt = mate_text or (f"M{abs(mate)}" if mate else "#")
        else:
            cp = cp or 0
            white_ahead = cp >= 0
            ratio = 0.5 + 0.5 * math.tanh(max(-1500, min(1500, cp)) / 400.0)
            txt = f"{abs(cp) / 100:.1f}"
        self.white_part.style(f"height: {ratio * 100:.1f}%")
        self.val.set_text(txt)
        # The number sits at the leading side's end of the bar, in that
        # side's contrasting colour
        at_white_end = white_ahead
        at_bottom = at_white_end != self._flipped
        self.val.style(
            ("top: auto; bottom: 2px;" if at_bottom else "top: 2px; bottom: auto;")
            + (" color: #222;" if white_ahead else " color: #EEE;"))
