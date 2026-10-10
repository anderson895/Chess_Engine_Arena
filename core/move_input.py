# ═══════════════════════════════════════════════════════════
#  core/move_input.py — Making a move by hand
#
#  Click a piece and then its square, or drag it there. The live game, a
#  tournament's manual seat and the review's what-if moves all take their
#  moves through one of these. Against an engine a move can also be made
#  in advance, while the engine thinks — a premove, as on chess.com and
#  Lichess.
# ═══════════════════════════════════════════════════════════

import inspect

from core.constants import BISHOP_D, KING_D, KNIGHT_D, QUEEN_D, ROOK_D


def square_name(r, c):
    """'e4' for board (row, col)."""
    return f"{chr(ord('a') + c)}{8 - r}"


def premove_targets(board, r, c):
    """
    Squares the piece on (r, c) might move to once its side is to move:
    wherever the piece's own way of moving reaches, whatever stands in the
    way now — the opponent's move may clear or fill any square, and a
    premove onto a square held by one's own piece is the recapture waiting
    for the opponent to take it (Lichess's chessground does the same).
    Whether the move is legal is settled when it is played.
    """
    piece = board.get(r, c)
    if not piece or piece == '.':
        return set()
    white = piece.isupper()
    kind = piece.lower()
    out = set()

    def add(tr, tc):
        if 0 <= tr < 8 and 0 <= tc < 8 and (tr, tc) != (r, c):
            out.add((tr, tc))

    if kind == 'p':
        step = -1 if white else 1
        add(r + step, c)
        if r == (6 if white else 1):
            add(r + 2 * step, c)
        add(r + step, c - 1)
        add(r + step, c + 1)
    elif kind == 'n':
        for dr, dc in KNIGHT_D:
            add(r + dr, c + dc)
    elif kind == 'k':
        for dr, dc in KING_D:
            add(r + dr, c + dc)
        home = 7 if white else 0
        rights = board.castling or ''
        if (r, c) == (home, 4):
            if ('K' if white else 'k') in rights:
                add(home, 6)
            if ('Q' if white else 'q') in rights:
                add(home, 2)
    else:
        for dr, dc in {'b': BISHOP_D, 'r': ROOK_D, 'q': QUEEN_D}[kind]:
            tr, tc = r + dr, c + dc
            while 0 <= tr < 8 and 0 <= tc < 8:
                out.add((tr, tc))
                tr += dr
                tc += dc
    return out


class MoveInput:
    """
    The piece picked up on a board, and the legal moves from it.

    board       : callable → the Board to move on, or None while no move
                  can be made there
    on_move     : callable(uci), may be async — a legal move was made
    can_move    : callable → whether moves are taken right now
    promote     : callable(colour 'w'|'b') → 'q', 'r', 'b' or 'n', may be
                  async; without one a pawn always becomes a queen
    can_premove : callable → whether, while no move is taken, the side not
                  to move may queue one for its turn (a person waiting on
                  an engine)
    on_premove  : callable(uci) — such a move was queued. It is not checked
                  here: whoever plays it checks it is legal by then. A
                  pawn queued to the last rank becomes a queen.
    """

    def __init__(self, board, on_move, can_move=None, promote=None,
                 can_premove=None, on_premove=None):
        self._board_of = board
        self._on_move = on_move
        self._can_move = can_move or (lambda: True)
        self._promote = promote
        self._can_premove = can_premove or (lambda: False)
        self._on_premove = on_premove
        self.selected = None              # (row, col) of the piece in hand

    def _board(self):
        board = self._board_of()
        return board if board is not None and self._can_move() else None

    def _premove_board(self):
        """The board to queue a move on, while that is what a click does."""
        if self._on_premove is None or self._board() is not None:
            return None
        board = self._board_of()
        return board if board is not None and self._can_premove() else None

    @staticmethod
    def _waiting_white(board):
        """True when the side queueing a move — the one not to move — is White."""
        return board.turn == "b"

    def movable(self):
        """Squares of the pieces that may move now — or be premoved."""
        board = self._board()
        if board is not None:
            return {(m[0], m[1]) for m in board.legal_moves()}
        board = self._premove_board()
        if board is None:
            return set()
        white = self._waiting_white(board)
        return {(r, c) for r in range(8) for c in range(8)
                if board.board[r][c] != '.'
                and board.board[r][c].isupper() == white}

    def dests(self):
        """Squares the piece in hand can go to (or be premoved to)."""
        if self.selected is None:
            return set()
        board = self._board()
        if board is not None:
            return {(m[2], m[3]) for m in board.legal_moves()
                    if (m[0], m[1]) == self.selected}
        board = self._premove_board()
        return premove_targets(board, *self.selected) if board else set()

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
        Returns 'move' once a move is made, 'premove' once one is queued,
        'select' when only the piece in hand changed, 'cancel' for a click
        that queues nothing while moves can only be queued (it drops a
        queued move), None when nothing happened.
        """
        board = self._board()
        if board is None:
            return self._premove_click(r, c)
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

    def _premove_click(self, r, c):
        """click() while moves can only be queued for the coming turn."""
        board = self._premove_board()
        if board is None:
            return None
        piece = board.get(r, c)
        own = bool(piece and piece != "."
                   and piece.isupper() == self._waiting_white(board))
        if self.selected is None:
            if own:
                self.selected = (r, c)
                return "select"
            return "cancel"
        if (r, c) == self.selected:
            self.selected = None
            return "select"
        # A target wins over picking up another piece: a premove onto one's
        # own piece is the recapture
        if (r, c) in premove_targets(board, *self.selected):
            fr, fc = self.selected
            self.selected = None
            uci = square_name(fr, fc) + square_name(r, c)
            if board.get(fr, fc).lower() == 'p' and r in (0, 7):
                uci += 'q'
            self._on_premove(uci)
            return "premove"
        if own:
            self.selected = (r, c)
            return "select"
        self.selected = None
        return "cancel"

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
