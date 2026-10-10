# ═══════════════════════════════════════════════════════════
#  core/start_position.py — Where a game starts
#
#  A game can start from the standard position, from a book line played
#  out from it, or from any position set up by hand (a FEN) — with moves
#  already made from there. The Play tab, the Set Up Position dialog, the
#  review's "Continue from here" and the game on the board all pass one
#  of these around.
# ═══════════════════════════════════════════════════════════

from dataclasses import dataclass

from core.board import Board
from core.utils import custom_start


@dataclass(frozen=True)
class StartPosition:
    """
    fen   : the position the game starts from; None for the standard start.
            Kept as the board reads it (castling rights the pieces do not
            allow are dropped), so the engines are told exactly the position
            the board plays.
    moves : UCI moves already played from it before the players take over —
            a book line, or moves made while setting up. They are part of
            the game's record but are never graded live or taken back.
    label : what the Play tab calls it.

    Raises ValueError for a FEN that cannot be read.
    """
    fen: str | None = None
    moves: tuple = ()
    label: str = "Normal start"

    def __post_init__(self):
        fen = custom_start(self.fen)
        if fen:
            fen = custom_start(Board.parse_fen(fen).to_fen())
        object.__setattr__(self, "fen", fen)
        object.__setattr__(self, "moves", tuple(self.moves or ()))

    @property
    def is_standard(self):
        """True for the normal start with nothing played."""
        return self.fen is None and not self.moves

    def board(self):
        """
        The position the players take over from, with the moves in its
        history. Raises ValueError if one of the moves is illegal.
        """
        board = Board()
        board.reset(self.fen)
        for uci in self.moves:
            board.apply_uci(uci)
        return board

    def problem(self):
        """Why no game can start here (core.board's position_problem), or None."""
        try:
            return self.board().position_problem()
        except ValueError as e:
            return str(e)
