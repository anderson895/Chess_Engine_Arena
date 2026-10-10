# ═══════════════════════════════════════════════════════════
#  review.py — Game review: move classification and accuracy
#
#  Classes follow chess.com's published definitions. Every move is
#  graded by the expected points it gave away (Best 0, Excellent ≤ .02,
#  Good ≤ .05, Inaccuracy ≤ .10, Mistake ≤ .20, Blunder above), then
#  three special classes are layered on top:
#
#    Brilliant — a good piece sacrifice: the move is (nearly) the best,
#                the mover is not worse afterwards, was not winning
#                anyway, and leaves material that can be taken.
#    Great     — the only good move: the runner-up loses a lot.
#    Miss      — the opponent erred and the move handed the gift back.
#
#  Accuracy uses Lichess's published formula. Nothing here touches the
#  UI or the engine: callers pass in the engine's analysis of every
#  position (AnalyzerEngine.analyse), so a review can be recomputed from
#  a cache without searching again.
# ═══════════════════════════════════════════════════════════

import math
from dataclasses import dataclass, field

from core.board import Board, SEE_VALUES, parse_uci
from core.constants import QUALITY_SYMBOLS
from core.opening_book import opening_label
from core.utils import custom_start, start_ply

# Classes in review-table order. "Forced" is graded but not tabled.
TABLE_ORDER = ["Brilliant", "Great", "Book", "Best", "Excellent", "Good",
               "Inaccuracy", "Mistake", "Miss", "Blunder"]

PIECE_NAMES = {'p': "pawn", 'n': "knight", 'b': "bishop",
               'r': "rook", 'q': "queen", 'k': "king"}

# Lichess's win% curve: win% = 100 / (1 + e^(-k·cp))
WIN_K = 0.00368208

# Thresholds, in expected points (0..1) from the mover's side
EXCELLENT_MAX  = 0.02
GOOD_MAX       = 0.05
INACCURACY_MAX = 0.10
MISTAKE_MAX    = 0.20
TIE_WITH_BEST  = 0.005   # a different move this close to the top one is Best too
WINNING_ANYWAY = 0.93    # ≈ +7: past this a sacrifice proves nothing
BRILLIANT_MIN  = 0.45    # not worse after it (a sacrifice that saves a draw counts)
ONLY_MOVE_GAP  = 0.10    # runner-up this much worse → the move was the only one
GREAT_ALT_MAX  = 0.80    # …and the runner-up must not still be winning
GREAT_MIN      = 0.40
MISS_SLACK     = 0.05
SAC_MIN        = 2       # net material given up, in pawns: a minor piece for a
                         # pawn or the exchange — not a trade that drops a pawn

# Accuracy and the graph use Lichess's convention: evaluations are capped
# at ±10 pawns and a forced mate counts as the cap, so a won position
# drifting from +15 to +9 does not read as a slip.
ACC_CAP = 1000


# ═══════════════════════════════════════════════════════════
#  Scores
# ═══════════════════════════════════════════════════════════

def expected_points(cp=None, mate=None):
    """Expected score (0..1) for the side whose point of view cp/mate is in."""
    if mate is not None:
        return 1.0 if mate > 0 else 0.0     # mate 0: already checkmated
    if cp is None:
        return 0.5
    return 1.0 / (1.0 + math.exp(-WIN_K * cp))


def line_ep(line):
    """Expected points of an analysis line, for the side to move."""
    if not line:
        return 0.5
    return expected_points(line.get("cp"), line.get("mate"))


def _top(analysis):
    lines = (analysis or {}).get("lines") or []
    return lines[0] if lines else None


def _second(analysis):
    lines = (analysis or {}).get("lines") or []
    return lines[1] if len(lines) > 1 else None


def white_pov(analysis, turn):
    """
    (cp, mate) of a position's top line from White's side, or (None, None).
    *turn* is the side to move there ('w' or 'b') — the side the engine
    scores from. Checkmate on the board is mate 0, with cp ±1 saying who
    delivered it.
    """
    top = _top(analysis)
    if top is None:
        return None, None
    sign = 1 if turn == 'w' else -1
    cp, mate = top.get("cp"), top.get("mate")
    if mate is not None:
        if mate == 0:
            return -sign, 0                   # the side to move is mated
        return None, sign * mate
    return (sign * cp if cp is not None else None), None


def white_win_pct(analysis, turn):
    """
    White's win% (0..100) in an analysed position with *turn* to move, or
    None — capped at ±10 pawns, mates included, for accuracy and the graph.
    """
    top = _top(analysis)
    if top is None:
        return None
    mate, cp = top.get("mate"), top.get("cp")
    if mate is not None:
        cp = ACC_CAP if mate > 0 else -ACC_CAP
    cp = max(-ACC_CAP, min(ACC_CAP, cp or 0))
    ep = expected_points(cp)
    return 100.0 * (ep if turn == 'w' else 1.0 - ep)


def move_number(ply):
    """
    '5.' before White's 5th move (ply 9), '5...' before Black's (ply 10).
    *ply* counts from the standard start; a game set up from a position
    adds the plies before it (GameAnalyst.number does).
    """
    return f"{(ply + 1) // 2}{'.' if ply % 2 else '...'}"


def format_eval(cp, mate):
    """'+1.25', '-0.40', 'M3', '-M2' (White's side), or '' when unknown."""
    if mate is not None:
        if mate == 0:
            return "#"
        return f"M{mate}" if mate > 0 else f"-M{-mate}"
    if cp is None:
        return ""
    return f"{cp / 100:+.2f}"


# ═══════════════════════════════════════════════════════════
#  Material that can be taken
# ═══════════════════════════════════════════════════════════

def _other(color):
    return 'b' if color == 'w' else 'w'


def _owner(piece):
    return 'w' if piece.isupper() else 'b'


def en_prise(board, color):
    """
    {square: loss} for *color*'s knights, bishops, rooks and queens that
    the other side could win material from by capturing now — as if it
    were its move. The opening capture must be legal (so pins and checks
    count); the exchange that follows is settled by SEE.
    """
    opp = _other(color)
    b = board if board.turn == opp else board.with_turn(opp)
    first = {}
    for fr, fc, tr, tc, promo in b.legal_moves():
        if promo not in (None, 'q'):
            continue
        target = b.board[tr][tc]
        if (target == '.' or target.lower() in ('p', 'k')
                or _owner(target) != color):
            continue
        value = SEE_VALUES[b.board[fr][fc].lower()]
        cur = first.get((tr, tc))
        if cur is None or value < SEE_VALUES[b.board[cur[0]][cur[1]].lower()]:
            first[(tr, tc)] = (fr, fc)
    out = {}
    for (r, c), sq in first.items():
        gain = b.see(r, c, opp, first=sq)
        if gain > 0:
            out[(r, c)] = gain
    return out


def _is_trapped(board, sq, color):
    """
    True if *color*'s piece on *sq* has no move that saves it: every move
    lands where it is lost for less than it takes. Assumes *color* to move.
    """
    b = board if board.turn == color else board.with_turn(color)
    r, c = sq
    opp = _other(color)
    for fr, fc, tr, tc, promo in b._pseudo(r, c):
        after = b._apply_raw(fr, fc, tr, tc, promo)
        if after.in_check(color):
            continue
        took = b.board[tr][tc]
        taken = SEE_VALUES[took.lower()] if took != '.' else 0
        if taken - after.see(tr, tc, opp) >= 0:
            return False
    return True


def _counter_threat(board, sq, value, color):
    """
    True if taking *color*'s piece on *sq* would let *color* win about as
    much straight back somewhere else — the "sacrifice" is then a trade
    rather than an offer (e.g. a knight left hanging while the opponent's
    queen is attacked).
    """
    opp = _other(color)
    b = board if board.turn == opp else board.with_turn(opp)
    best = None
    for mv in b.legal_moves():
        if (mv[2], mv[3]) == sq and mv[4] in (None, 'q'):
            v = SEE_VALUES[b.board[mv[0]][mv[1]].lower()]
            if best is None or v < best[0]:
                best = (v, mv)
    if best is None:
        return False
    after = b._apply_raw(*best[1])
    for (r, c), regain in en_prise(after, opp).items():
        if (r, c) != sq and regain >= value - 1:
            return True
    return False


def sacrifice(before, after, uci, earlier=None):
    """
    The piece (lower-case letter) the move offers, or None.

    A piece counts as offered when, after the move, the opponent could
    win material by taking it and it is:
      - the piece that just moved (unless it was trapped and lost anyway),
      - a piece the move left newly exposed (a defender moved away), or
      - a piece the opponent has just attacked that could have been saved
        but was left where it stands — a threat deliberately ignored.
    The move must give up clearly more than it takes: the piece is worth
    more than anything captured and the net loss is at least SAC_MIN, so
    minor pieces for a pawn, exchange sacrifices and queen sacrifices
    count, but pawn sacrifices and trades that merely drop a pawn do not.
    A move that rescues a piece and leaves a lesser one to its fate is not
    a sacrifice, and neither is leaving a piece whose capture loses the
    taker as much straight back.

    *earlier* is the position before the opponent's last move. A piece
    that was already hanging there was offered on an earlier move, and
    leaving it hanging again is not a fresh sacrifice.
    """
    fr, fc, tr, tc, promo = parse_uci(uci)
    moved = before.board[fr][fc]
    if moved == '.':
        return None
    mover = _owner(moved)

    target = before.board[tr][tc]
    if target != '.':
        gained = SEE_VALUES[target.lower()]
    elif moved.lower() == 'p' and fc != tc:
        gained = 1                                  # en passant
    else:
        gained = 0

    hung_after = en_prise(after, mover)
    if not hung_after:
        return None
    hung_before = en_prise(before, mover)

    def origin(sq):
        return (fr, fc) if sq == (tr, tc) else sq

    # Rescue: every piece hanging now was hanging before, and fewer are
    if (len(hung_after) < len(hung_before)
            and all(origin(sq) in hung_before for sq in hung_after)):
        return None

    hung_earlier = None
    best = None
    for sq, loss in hung_after.items():
        piece = after.board[sq[0]][sq[1]]
        value = SEE_VALUES[piece.lower()]
        if value <= gained or loss - gained < SAC_MIN:
            continue
        was_hanging = origin(sq) in hung_before
        if sq == (tr, tc):
            if was_hanging and _is_trapped(before, (fr, fc), mover):
                continue                            # desperado: lost anyway
        elif was_hanging:
            if earlier is not None:
                if hung_earlier is None:
                    hung_earlier = en_prise(earlier, mover)
                if sq in hung_earlier:
                    continue                        # offered before, still declined
            if _is_trapped(before, sq, mover):
                continue                            # could not be saved
        if _counter_threat(after, sq, value, mover):
            continue
        if best is None or loss - gained > best[0]:
            best = (loss - gained, piece.lower())
    return best[1] if best else None


def previous_context(prev_move, a_opp_turn, a_mover_last):
    """
    What classify_move needs to know about the moves before this one.

    prev_move    : the opponent's last move (anything with a .loss), or None
    a_opp_turn   : analysis of the position the opponent moved from
    a_mover_last : analysis of the position the mover last moved from
    """
    ctx = {}
    if prev_move is not None and getattr(prev_move, "loss", None) is not None:
        top = _top(a_opp_turn)
        if top is not None:
            ctx["loss"] = prev_move.loss
            ctx["ep_mover_before"] = 1.0 - line_ep(top)
    top = _top(a_mover_last)
    ctx["mover_had_mate"] = bool(top and (top.get("mate") or 0) > 0)
    return ctx or None


def _captures_en_prise(before, uci):
    """True if the move takes a piece the mover could already win."""
    fr, fc, tr, tc, _ = parse_uci(uci)
    target = before.board[tr][tc]
    if target == '.':
        return False
    return before.see(tr, tc, before.turn, first=(fr, fc)) > 0


# ═══════════════════════════════════════════════════════════
#  One move
# ═══════════════════════════════════════════════════════════

@dataclass
class Verdict:
    cls: str | None
    loss: float | None = None       # expected points given away
    ep_best: float | None = None    # mover's expected points with the best move
    ep_after: float | None = None   # mover's expected points after the move
    best_uci: str | None = None
    sacrificed: str | None = None   # piece letter, for Brilliant
    missed_mate: bool = False
    allows_mate: bool = False


def classify_move(before, after, uci, a_before, a_after, *,
                  book=False, prev=None, earlier=None):
    """
    Grade one move.

    before, after : Board — the position before (mover to move) and after.
    a_before, a_after : AnalyzerEngine.analyse() results for those
        positions (MultiPV 2 for *a_before*), either may be None.
    book : the position reached is opening theory.
    prev : previous_context() — what the opponent's last move gave away,
        where the mover stood before it, and whether the mover already
        had a forced mate — or None.
    earlier : Board before the opponent's last move, or None (so a piece
        left hanging for several moves is only a sacrifice once).
    """
    legal = before.legal_moves()
    if book:
        return Verdict("Book", loss=0.0)
    if len(legal) == 1:
        return Verdict("Forced", loss=0.0,
                       best_uci=_top(a_before).get("move") if _top(a_before) else None)

    top, second = _top(a_before), _second(a_before)
    if top is None:
        return Verdict(None)

    mover = before.turn
    best_uci = top.get("move")
    ep_best = line_ep(top)
    if uci == best_uci:
        ep_after = ep_best
    elif second is not None and uci == second.get("move"):
        ep_after = line_ep(second)
    elif _top(a_after) is not None:
        ep_after = 1.0 - line_ep(_top(a_after))
    else:
        return Verdict(None, best_uci=best_uci)
    loss = max(0.0, ep_best - ep_after)

    checkmate = after.in_check(after.turn) and not after.legal_moves()
    v = Verdict(None, loss=loss, ep_best=ep_best, ep_after=ep_after,
                best_uci=best_uci)
    after_top = _top(a_after)
    v.allows_mate = bool(after_top and (after_top.get("mate") or 0) > 0)

    # ── Base class by expected points lost ────────────────
    mate_before = top.get("mate")
    mate_after = -after_top["mate"] if after_top and after_top.get("mate") else None
    if uci == best_uci or checkmate:
        v.cls = "Best"
    elif mate_before and mate_after and (mate_before > 0) == (mate_after > 0):
        # Mate on the board before and after, for the same side: what
        # matters is how much longer the mate (or the defence) got
        if mate_before > 0:
            v.cls = ("Best" if mate_after <= mate_before - 1 else
                     "Excellent" if mate_after <= mate_before + 2 else "Good")
        else:
            v.cls = "Best" if mate_after <= mate_before + 1 else "Good"
    elif loss < TIE_WITH_BEST:
        v.cls = "Best"
    elif loss <= EXCELLENT_MAX:
        v.cls = "Excellent"
    elif loss <= GOOD_MAX:
        v.cls = "Good"
    elif loss <= INACCURACY_MAX:
        v.cls = "Inaccuracy"
    elif loss <= MISTAKE_MAX:
        v.cls = "Mistake"
    else:
        v.cls = "Blunder"

    # ── Miss: a chance the opponent handed over, handed back ──
    if loss >= INACCURACY_MAX and v.cls in ("Mistake", "Blunder", "Inaccuracy"):
        if (mate_before or 0) > 0 and ep_after >= 0.5:
            v.cls, v.missed_mate = "Miss", True
        elif (prev and prev.get("loss") is not None
                and prev["loss"] >= INACCURACY_MAX
                and prev.get("ep_mover_before") is not None
                and ep_after >= prev["ep_mover_before"] - MISS_SLACK):
            v.cls = "Miss"

    if checkmate or v.cls not in ("Best", "Excellent"):
        return v

    in_check = before.in_check(mover)
    promotes = len(uci) > 4

    # The best alternative to the move played: the runner-up if the move
    # was the top line, the top line otherwise
    alt = second if uci == best_uci else top
    alt_ep = line_ep(alt) if alt is not None else None

    # ── Brilliant: a sound sacrifice ──────────────────────
    if (not in_check and not promotes and ep_after >= BRILLIANT_MIN
            and alt_ep is not None and alt_ep < WINNING_ANYWAY):
        piece = sacrifice(before, after, uci, earlier)
        if piece:
            v.cls, v.sacrificed = "Brilliant", piece
            return v

    # ── Great: the only good move ─────────────────────────
    # Not the next move of a mate already on the board, not a free capture
    # or a recapture (obvious, however forced), and only when the
    # runner-up would have changed the outcome rather than merely won less
    if (uci == best_uci and second is not None and not in_check
            and not promotes
            and ep_best - line_ep(second) >= ONLY_MOVE_GAP
            and line_ep(second) < GREAT_ALT_MAX
            and ep_after >= GREAT_MIN
            and not (prev and prev.get("mover_had_mate"))
            and not _captures_en_prise(before, uci)):
        v.cls = "Great"
    return v


# ═══════════════════════════════════════════════════════════
#  Accuracy and phases
# ═══════════════════════════════════════════════════════════

def move_accuracy(win_before, win_after):
    """Lichess move accuracy from the mover's win% before and after (0..100)."""
    if win_after >= win_before:
        return 100.0
    raw = (103.1668100711649
           * math.exp(-0.04354415386753951 * (win_before - win_after))
           - 3.166924740191411)
    return max(0.0, min(100.0, raw + 1))


def _stdev(xs):
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def game_accuracy(white_wins, accuracies, first='w'):
    """
    Per-side accuracy, Lichess style: the mean of a volatility-weighted
    mean and a harmonic mean of the side's move accuracies. Calm stretches
    weigh less than sharp ones, and the harmonic mean makes one bad blunder
    cost more than many small slips.

    white_wins : White's win% for every position, start included.
    accuracies : accuracy of each move (None where unknown).
    first      : the side that made the first move ('b' for a game set up
                 with Black to move).
    Returns {'w': float | None, 'b': float | None}.
    """
    n = len(accuracies)
    window = max(2, min(8, n // 10))
    vals = [w if w is not None else 50.0 for w in white_wins]
    windows = [vals[:window]] * max(0, window - 2)
    if len(vals) <= window:
        windows.append(vals)
    else:
        windows += [vals[i:i + window] for i in range(len(vals) - window + 1)]
    weights = [max(0.5, min(12.0, _stdev(w))) for w in windows]

    out = {}
    shift = 0 if first == 'w' else 1
    for side, parity in (('w', 0), ('b', 1)):
        pairs = [(accuracies[i], weights[i] if i < len(weights) else 0.5)
                 for i in range(n)
                 if (i + shift) % 2 == parity and accuracies[i] is not None]
        if not pairs:
            out[side] = None
            continue
        weighted = sum(a * w for a, w in pairs) / sum(w for _, w in pairs)
        harmonic = len(pairs) / sum(1.0 / max(a, 1.0) for a, _ in pairs)
        out[side] = (weighted + harmonic) / 2
    return out


def _majors_minors(board):
    return sum(1 for row in board.board for p in row if p.lower() in 'nbrq')


def _backrank_sparse(board):
    white = sum(1 for p in board.board[7] if p != '.' and p.isupper())
    black = sum(1 for p in board.board[0] if p != '.' and p.islower())
    return white < 4 or black < 4


def phase_starts(boards, ply0=0):
    """
    (middlegame_ply, endgame_ply) after Lichess's game divider, simplified:
    the middlegame starts once ten or fewer pieces remain, a back rank has
    emptied out, or move 15 is reached; the endgame once six or fewer
    pieces remain. Each is len(boards) when the game never got there.
    *ply0* is how many plies were played before boards[0] (a game set up
    from a position), so "move 15" means the same in every game.
    """
    n = len(boards)
    mid = next((i for i, b in enumerate(boards)
                if _majors_minors(b) <= 10 or _backrank_sparse(b)
                or ply0 + i >= 30), n)
    end = next((i for i, b in enumerate(boards)
                if i >= mid and _majors_minors(b) <= 6), n)
    return mid, end


PHASES = ("Opening", "Middlegame", "Endgame")


def _phase_grade(moves):
    """One icon for a stretch of a player's moves, or None if there were none."""
    if not moves:
        return None
    classes = [m.cls for m in moves if m.cls]
    if classes and all(c in ("Book", "Forced") for c in classes):
        return "Book"
    for special in ("Brilliant", "Great"):
        if special in classes:
            return special
    accs = [m.accuracy for m in moves if m.accuracy is not None]
    if not accs:
        return None
    acc = sum(accs) / len(accs)
    for floor, cls in ((95, "Best"), (85, "Excellent"), (70, "Good"),
                       (55, "Inaccuracy"), (40, "Mistake")):
        if acc >= floor:
            return cls
    return "Blunder"


# ═══════════════════════════════════════════════════════════
#  Whole game
# ═══════════════════════════════════════════════════════════

@dataclass
class MoveReview:
    ply: int                        # 1 = the game's first move
    uci: str
    san: str
    color: str                      # 'w' or 'b'
    cls: str | None = None
    loss: float | None = None
    ep_after: float | None = None   # mover's expected points after the move
    accuracy: float | None = None
    eval_cp: int | None = None      # after the move, White's side
    eval_mate: int | None = None
    best_uci: str | None = None
    best_san: str | None = None
    sacrificed: str | None = None
    missed_mate: bool = False
    allows_mate: bool = False
    comment: str = ""
    ply0: int = 0                   # plies played before the game's start
                                    # position (0 from the standard start)

    @property
    def symbol(self):
        """'!!', '?' … for the classes that have an annotation glyph."""
        return QUALITY_SYMBOLS.get(self.cls, "")

    @property
    def number(self):
        """The move number as written before it: '5.' for White, '5...' for Black."""
        return move_number(self.ply0 + self.ply)

    @property
    def numbered_san(self):
        """'5. Nxe5', '5... Bxd1'."""
        return f"{self.number} {self.san}"

    @property
    def evaluation(self):
        """(cp, mate) after the move from White's side, or None if unknown."""
        if self.eval_cp is None and self.eval_mate is None:
            return None
        return self.eval_cp, self.eval_mate


@dataclass
class GameReview:
    moves: list = field(default_factory=list)          # [MoveReview | None]
    fens: list = field(default_factory=list)           # position after each ply, start first
    white_wins: list = field(default_factory=list)     # White win% per position
    openings: list = field(default_factory=list)       # (eco, name) after each ply
    counts: dict = field(default_factory=dict)         # {'w': {cls: n}, 'b': …}
    accuracy: dict = field(default_factory=dict)       # {'w': float | None, 'b': …}
    phases: dict = field(default_factory=dict)         # {'w': {phase: cls}, 'b': …}
    middlegame_ply: int = 0
    endgame_ply: int = 0
    complete: bool = False                             # every position analysed


def san_line(fen, pv, limit=6):
    """SAN of the first *limit* moves of a UCI line played from *fen*."""
    b = Board.from_fen(fen)
    out = []
    for uci in (pv or [])[:limit]:
        try:
            san, _ = b.apply_uci(uci)
        except ValueError:
            break
        out.append(san)
    return out


def comment_for(m):
    """Coach line for a reviewed move."""
    san, best = m.san, m.best_san
    tail = f" {best} was best." if best and best != san else ""
    cls = m.cls
    if cls is None:
        return ""
    if "#" in san:
        return f"{san} is checkmate."
    if cls == "Book":
        return f"{san} is a book move."
    if cls == "Forced":
        return f"{san} is the only legal move."
    if cls == "Brilliant":
        what = PIECE_NAMES.get(m.sacrificed or '', "material")
        return f"{san} is brilliant! It sacrifices the {what}."
    if cls == "Great":
        what = ("keeps the advantage" if (m.ep_after or 0) >= 0.65
                else "holds the position")
        return f"{san} is a great move — the only one that {what}."
    if cls == "Best":
        return f"{san} is the best move."
    if cls == "Excellent":
        return f"{san} is excellent."
    if cls == "Good":
        return f"{san} is good.{tail}"
    if cls == "Miss":
        if m.missed_mate:
            return f"{san} misses a forced checkmate.{tail}"
        return f"{san} misses the chance to punish the opponent's mistake.{tail}"
    mate_note = " It allows a forced checkmate." if m.allows_mate else ""
    if cls == "Inaccuracy":
        return f"{san} is an inaccuracy.{tail}"
    if cls == "Mistake":
        return f"{san} is a mistake.{mate_note}{tail}"
    if cls == "Blunder":
        return f"{san} is a blunder.{mate_note}{tail}"
    return ""


class GameAnalyst:
    """
    One game, move by move — the single place where a game is followed,
    its opening named and its moves graded. The live game, the tournament
    runner and the review screen all drive one of these, so a move is
    judged the same way wherever it was played.

    Positions are analysed either on demand through *analyse* — a
    callable taking the UCI history up to a position and the game's start
    FEN (None for the standard start), and returning
    AnalyzerEngine.analyse() output — or handed in with set_analysis()
    by a caller that runs the engine itself. Without either the analyst
    still tracks the opening, so naming works with no engine at all.

    A game set up from a position passes its FEN as *start_fen*: the
    moves are played from there, and their numbers count on from it.
    """

    def __init__(self, book=None, analyse=None, start_fen=None):
        self.book = book if book is not None and book.loaded else None
        self._analyse = analyse
        self.start_fen = custom_start(start_fen)    # None: the standard start
        self.ply0 = start_ply(self.start_fen)       # plies before that position
        self.reset()

    def reset(self):
        start = Board.from_fen(self.start_fen) if self.start_fen else Board()
        self.moves = []                  # UCI, one per ply
        self.sans = []
        self.boards = [start]            # position after each ply; [0] = start
        self.analyses = [None]           # engine analysis of each position
        self.reviews = []                # MoveReview per ply, None until graded
        self._tracker = (self.book.tracker(start if self.start_fen else None)
                         if self.book else None)
        tracker = self._tracker
        # (eco, name) as it stands after each ply, and whether each
        # position is theory — the standard start always is
        self.openings = [(tracker.eco, tracker.name) if tracker else (None, None)]
        self.in_book = [tracker.in_book if tracker else True]

    # ── Following the game ────────────────────────────────

    @property
    def ply(self):
        """Number of moves played so far."""
        return len(self.moves)

    def record(self, uci):
        """
        Play a move. Cheap — no engine — so it can run on every move as it
        happens. Returns the SAN; raises ValueError if the move is illegal.
        """
        board = self.boards[-1].copy()
        san, _ = board.apply_uci(uci)
        self.moves.append(uci)
        self.sans.append(san)
        self.boards.append(board)
        self.analyses.append(None)
        self.reviews.append(None)
        if self._tracker is not None:
            self._tracker.update(board)
            self.openings.append((self._tracker.eco, self._tracker.name))
            self.in_book.append(self._tracker.in_book)
        else:
            self.openings.append((None, None))
            self.in_book.append(False)
        return san

    @property
    def opening(self):
        """(eco, name) of the game's opening as it stands now."""
        return self.openings[-1]

    @property
    def opening_label(self):
        """'C60 · Ruy Lopez', or '' before the game reached a named position."""
        return opening_label(*self.opening)

    def number(self, ply):
        """'5.' or '5...': the move number written before the move that reached *ply*."""
        return move_number(self.ply0 + ply)

    # ── Engine analysis ───────────────────────────────────

    def set_analysis(self, i, analysis):
        """Hand in the analysis of the position after *i* plies."""
        self.analyses[i] = analysis

    def analysis(self, i):
        """Analysis of the position after *i* plies, run now if missing."""
        if self.analyses[i] is None and self._analyse is not None:
            self.analyses[i] = self._analyse(" ".join(self.moves[:i]),
                                             self.start_fen)
        return self.analyses[i]

    def eval_after(self, i):
        """
        (cp, mate) of the position after *i* plies from White's side.
        Checkmate on the board is mate 0, with cp ±1 saying who delivered it.
        """
        board = self.boards[i]
        if board.in_check(board.turn) and not board.legal_moves():
            return (-1 if board.turn == 'w' else 1), 0
        return white_pov(self.analyses[i], board.turn)

    # ── Grading ───────────────────────────────────────────

    def grade(self, ply):
        """Classify the move that reached position *ply* (1-based)."""
        i = ply
        before, after = self.boards[i - 1], self.boards[i]
        uci = self.moves[i - 1]
        a_before, a_after = self.analysis(i - 1), self.analysis(i)
        prev = previous_context(self.reviews[i - 2] if i >= 2 else None,
                                self.analyses[i - 2] if i >= 2 else None,
                                self.analyses[i - 3] if i >= 3 else None)
        v = classify_move(before, after, uci, a_before, a_after,
                          book=self.in_book[i] and self.book is not None,
                          prev=prev,
                          earlier=self.boards[i - 2] if i >= 2 else None)

        m = MoveReview(ply=i, uci=uci, san=self.sans[i - 1],
                       color=before.turn,
                       cls=v.cls, loss=v.loss, ep_after=v.ep_after,
                       best_uci=v.best_uci,
                       sacrificed=v.sacrificed, missed_mate=v.missed_mate,
                       allows_mate=v.allows_mate, ply0=self.ply0)
        m.eval_cp, m.eval_mate = self.eval_after(i)

        # Accuracy from consecutive position evaluations
        wb = white_win_pct(a_before, before.turn)
        wa = white_win_pct(a_after, after.turn) if a_after else None
        if m.cls in ("Book", "Forced"):
            m.accuracy = 100.0
        elif wb is not None and wa is not None:
            m.accuracy = (move_accuracy(wb, wa) if m.color == 'w'
                          else move_accuracy(100.0 - wb, 100.0 - wa))

        if m.best_uci and m.best_uci != uci:
            best = san_line(before.to_fen(), [m.best_uci], 1)
            m.best_san = best[0] if best else None
        m.comment = comment_for(m)
        self.reviews[i - 1] = m
        return m

    def push(self, uci):
        """record() and grade() in one go, for callers on a worker thread."""
        self.record(uci)
        return self.grade(self.ply)

    def truncated(self, ply, analyse=None):
        """
        A new analyst for this game's first *ply* moves — a takeback, or
        the start of a side line — keeping every analysis and grade
        already made for them. A grade still being worked out for a later
        move lands on this old analyst and is lost with it. *analyse*
        replaces the way missing positions are analysed.
        """
        g = GameAnalyst(self.book, analyse or self._analyse, self.start_fen)
        for uci in self.moves[:ply]:
            g.record(uci)
        g.analyses[:ply + 1] = self.analyses[:ply + 1]
        g.reviews[:ply] = self.reviews[:ply]
        return g

    def best_line_san(self, ply, limit=6):
        """
        SAN of the engine's best line from the position the move *ply* was
        played in, or [] when that position has not been analysed.
        """
        lines = (self.analyses[ply - 1] or {}).get("lines") or []
        pv = lines[0].get("pv") if lines else None
        if not pv:
            rv = self.reviews[ply - 1]
            pv = [rv.best_uci] if rv and rv.best_uci else []
        return san_line(self.boards[ply - 1].to_fen(), pv, limit)

    # ── The whole game ────────────────────────────────────

    def summary(self):
        """The review of everything played and graded so far."""
        rv = GameReview()
        n = self.ply
        rv.moves = list(self.reviews)
        rv.fens = [b.to_fen() for b in self.boards]
        rv.white_wins = [white_win_pct(self.analyses[i], self.boards[i].turn)
                         for i in range(n + 1)]
        rv.openings = list(self.openings)
        rv.complete = all(a is not None for a in self.analyses)

        accuracies = [m.accuracy if m else None for m in self.reviews]
        rv.accuracy = game_accuracy(rv.white_wins, accuracies,
                                    self.boards[0].turn)
        rv.counts = {side: {cls: 0 for cls in TABLE_ORDER} for side in ('w', 'b')}
        for m in self.reviews:
            if m and m.cls in rv.counts[m.color]:
                rv.counts[m.color][m.cls] += 1

        rv.middlegame_ply, rv.endgame_ply = phase_starts(self.boards, self.ply0)
        for side in ('w', 'b'):
            mine = [m for m in self.reviews if m and m.color == side]
            rv.phases[side] = {
                "Opening":    _phase_grade([m for m in mine
                                            if m.ply <= rv.middlegame_ply]),
                "Middlegame": _phase_grade([m for m in mine
                                            if rv.middlegame_ply < m.ply <= rv.endgame_ply]),
                "Endgame":    _phase_grade([m for m in mine
                                            if m.ply > rv.endgame_ply]),
            }
        return rv


def review_game(uci_moves, analyses, book=None, start_fen=None):
    """
    Review a finished game from the analysis of each of its positions.

    uci_moves : the game's moves from its start position.
    analyses  : AnalyzerEngine.analyse() results, one per position —
                index i is the position after i plies. Missing ones may
                be None; the moves around them are left ungraded.
    book      : OpeningBook for naming the opening and spotting theory.
    start_fen : the start position, when not the standard one.
    """
    g = GameAnalyst(book, start_fen=start_fen)
    for uci in uci_moves:
        try:
            g.record(uci)
        except ValueError:
            break
    for i, analysis in enumerate(list(analyses or [])[:g.ply + 1]):
        g.set_analysis(i, analysis)
    for ply in range(1, g.ply + 1):
        g.grade(ply)
    return g.summary()
