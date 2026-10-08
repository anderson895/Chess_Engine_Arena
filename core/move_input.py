# ═══════════════════════════════════════════════════════════
#  core/move_input.py — Making a move by hand
#
#  Click a piece and then its square, or drag it there. The live game, a
#  tournament's manual seat and the review's what-if moves all take their
#  moves through one of these.
# ═══════════════════════════════════════════════════════════

import inspect


def square_name(r, c):
    """'e4' for board (row, col)."""
    return f"{chr(ord('a') + c)}{8 - r}"


class MoveInput:
    """
    The piece picked up on a board, and the legal moves from it.

    board    : callable → the Board to move on, or None while no move can
               be made there
    on_move  : callable(uci), may be async — a legal move was made
    can_move : callable → whether moves are taken right now
    promote  : callable(colour 'w'|'b') → 'q', 'r', 'b' or 'n', may be
               async; without one a pawn always becomes a queen
    """

    def __init__(self, board, on_move, can_move=None, promote=None):
        self._board_of = board
        self._on_move = on_move
        self._can_move = can_move or (lambda: True)
        self._promote = promote
        self.selected = None              # (row, col) of the piece in hand

    def _board(self):
        board = self._board_of()
        return board if board is not None and self._can_move() else None

    def movable(self):
        """Squares of the pieces that may move now."""
        board = self._board()
        return {(m[0], m[1]) for m in board.legal_moves()} if board else set()

    def dests(self):
        """Squares the piece in hand can go to."""
        board = self._board()
        if board is None or self.selected is None:
            return set()
        return {(m[2], m[3]) for m in board.legal_moves()
                if (m[0], m[1]) == self.selected}

    def pick(self, r, c):
        """Pick up the piece on (r, c) if it may move. True if that changed anything."""
        if (r, c) in self.movable() and self.selected != (r, c):
            self.selected = (r, c)
            return True
        return False

    def clear(self):
        self.selected = None

    async def click(self, r, c):
        """
        A click on (r, c): pick a piece up, put it down, or play it there.
        Returns 'move' once a move is made, 'select' when only the piece in
        hand changed, None when nothing did.
        """
        board = self._board()
        if board is None:
            return None
        white = board.turn == "w"
        piece = board.get(r, c)
        own = bool(piece and piece != "." and piece.isupper() == white)
        if self.selected is None:
            if not own:
                return None
            self.selected = (r, c)
            return "select"
        if (r, c) == self.selected:
            self.selected = None
            return "select"
        if own:
            self.selected = (r, c)
            return "select"

        fr, fc = self.selected
        self.selected = None
        matching = [m for m in board.legal_moves()
                    if m[0] == fr and m[1] == fc and m[2] == r and m[3] == c]
        if not matching:
            return "select"
        uci = square_name(fr, fc) + square_name(r, c)
        if any(m[4] for m in matching):
            uci += await self._promotion("w" if white else "b")
        played = self._on_move(uci)
        if inspect.isawaitable(played):
            await played
        return "move"

    async def drop(self, fr, fc, tr, tc):
        """A piece dragged from (fr, fc) and let go on (tr, tc)."""
        self.pick(fr, fc)                 # in case the drag start went unheard
        if self.selected != (fr, fc):
            return None
        return await self.click(tr, tc)

    async def _promotion(self, colour):
        choice = self._promote(colour) if self._promote else None
        if inspect.isawaitable(choice):
            choice = await choice
        return (choice or "q").lower()
