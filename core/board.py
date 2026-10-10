# ═══════════════════════════════════════════════════════════
#  board.py — Full chess rules engine (Board class)
# ═══════════════════════════════════════════════════════════

from core.constants import (
    START_FEN, PIECE_VALUES,
    ROOK_D, BISHOP_D, QUEEN_D, KNIGHT_D, KING_D,
)
from core.utils import valid

# Exchange values. The king is priced so it always recaptures last.
SEE_VALUES = {'p': 1, 'n': 3, 'b': 3, 'r': 5, 'q': 9, 'k': 100}


def parse_uci(uci):
    """
    (from_row, from_col, to_row, to_col, promo) of a UCI move such as
    'e7e8q' — rows count from rank 8 down, as on Board.board. Raises
    ValueError for text that is not shaped like a move.
    """
    if not uci or len(uci) < 4:
        raise ValueError(f"Bad UCI: {uci!r}")
    try:
        return (8 - int(uci[1]), ord(uci[0]) - ord('a'),
                8 - int(uci[3]), ord(uci[2]) - ord('a'),
                uci[4].lower() if len(uci) > 4 else None)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Bad UCI: {uci!r}") from e


def format_uci(fr, fc, tr, tc, promo=None):
    """The UCI text of a move given in board coordinates."""
    return f"{chr(ord('a') + fc)}{8 - fr}{chr(ord('a') + tc)}{8 - tr}{promo or ''}"


class Board:
    """
    Complete chess rules engine.

    Supports:
    - Full legal-move generation (including castling, en-passant, promotion)
    - UCI move application
    - SAN move building
    - Game-result detection (checkmate, stalemate, 50-move, threefold, insufficient)
    - Material counting
    - PGN move-history tracking
    """

    def __init__(self):
        self.board        = None
        self.turn         = 'w'
        self.castling     = 'KQkq'
        self.ep           = '-'
        self.halfmove     = 0
        self.fullmove     = 1
        self.move_history = []      # list of (uci, san, fen_after)
        self.pos_history  = {}      # position-key → repetition count
        self.cap_white    = []      # pieces captured by White
        self.cap_black    = []      # pieces captured by Black
        self._material_cache = None
        self._load_fen(START_FEN)

    # ── Initialisation ────────────────────────────────────

    def reset(self, fen=None):
        """Restore the starting position — the standard one, or *fen*."""
        self.__init__()
        if fen:
            self._load_fen(fen)

    def _load_fen(self, fen):
        parts = fen.split()
        self.board = []
        for row_str in parts[0].split('/'):
            row = []
            for ch in row_str:
                if ch.isdigit():
                    row.extend(['.'] * int(ch))
                else:
                    row.append(ch)
            self.board.append(row)
        self.turn     = parts[1] if len(parts) > 1 else 'w'
        self.castling = parts[2] if len(parts) > 2 else '-'
        self.ep       = parts[3] if len(parts) > 3 else '-'
        self.halfmove = int(parts[4]) if len(parts) > 4 else 0
        self.fullmove = int(parts[5]) if len(parts) > 5 else 1
        self._material_cache = None

    # ── FEN export ────────────────────────────────────────

    def to_fen(self):
        """Serialize the current position to a FEN string."""
        rows = []
        for row in self.board:
            e = 0; s = ''
            for cell in row:
                if cell == '.':
                    e += 1
                else:
                    if e:
                        s += str(e); e = 0
                    s += cell
            if e:
                s += str(e)
            rows.append(s)
        c = self.castling if self.castling else '-'
        return f"{'/'.join(rows)} {self.turn} {c} {self.ep} {self.halfmove} {self.fullmove}"

    def _pos_key(self):
        """Position key for threefold-repetition detection (pieces + turn + castling + ep)."""
        parts = self.to_fen().split()
        return ' '.join(parts[:4])

    def epd(self):
        """
        Position identity for looking positions up: placement, side to move,
        castling rights, and the en-passant square *only when an en-passant
        capture is actually legal*.

        The board records an en-passant square after every double pawn push,
        whether or not any pawn could take. Keeping it would split one
        position into two depending on the move order that reached it —
        1.e4 c5 2.Nf3 and 1.Nf3 c5 2.e4 must be the same Sicilian.
        """
        placement, turn, castling, ep = self.to_fen().split()[:4]
        if ep != '-' and not self._ep_capture_legal():
            ep = '-'
        return f"{placement} {turn} {castling} {ep}"

    def _ep_capture_legal(self):
        """True if the side to move has a legal en-passant capture."""
        if self.ep == '-':
            return False
        ec = ord(self.ep[0]) - ord('a')
        er = 8 - int(self.ep[1])
        pawn = 'P' if self.turn == 'w' else 'p'
        pr = er + 1 if self.turn == 'w' else er - 1
        for pc in (ec - 1, ec + 1):
            if valid(pr, pc) and self.board[pr][pc] == pawn:
                if not self._apply_raw(pr, pc, er, ec, None).in_check(self.turn):
                    return True
        return False

    @classmethod
    def from_fen(cls, fen):
        """A board set up from *fen*, with no move history."""
        b = cls()
        b._load_fen(fen)
        return b

    @classmethod
    def parse_fen(cls, text):
        """
        A board set up from FEN text a person typed or pasted. Unlike
        from_fen, which trusts its input, this checks it and raises
        ValueError saying what is wrong. Missing move counters default to
        0 and 1. Castling rights the pieces no longer allow, and an
        en-passant square no pawn has just made, are dropped — as chess.com
        and Lichess do. Whether the position can start a game is
        position_problem()'s question.
        """
        fields = (text or "").split()
        if not fields:
            raise ValueError("The FEN is empty")
        if len(fields) > 6:
            raise ValueError("A FEN has at most six fields")
        ranks = fields[0].split('/')
        if len(ranks) != 8:
            raise ValueError("The board needs 8 ranks separated by '/'")
        for i, rank in enumerate(ranks):
            width = 0
            for ch in rank:
                if ch in '12345678':
                    width += int(ch)
                elif ch in 'KQRBNPkqrbnp':
                    width += 1
                else:
                    raise ValueError(f"'{ch}' is not a piece (rank {8 - i})")
            if width != 8:
                raise ValueError(f"Rank {8 - i} has {width} squares, not 8")
        turn = fields[1] if len(fields) > 1 else 'w'
        if turn not in ('w', 'b'):
            raise ValueError("The side to move must be w or b")
        castling = fields[2] if len(fields) > 2 else '-'
        if castling != '-' and (any(ch not in 'KQkq' for ch in castling)
                                or len(set(castling)) != len(castling)):
            raise ValueError("Castling rights must be - or letters from KQkq")
        ep = fields[3] if len(fields) > 3 else '-'
        if ep != '-' and not (len(ep) == 2 and ep[0] in 'abcdefgh'
                              and ep[1] in '36'):
            raise ValueError(f"{ep} is not an en-passant square")
        try:
            halfmove = int(fields[4]) if len(fields) > 4 else 0
            fullmove = int(fields[5]) if len(fields) > 5 else 1
        except ValueError:
            raise ValueError("The move counters must be numbers") from None
        if halfmove < 0 or fullmove < 1:
            raise ValueError("The move counters are out of range")

        b = cls.from_fen(f"{fields[0]} {turn} {castling} {ep} "
                         f"{halfmove} {fullmove}")
        allowed = b.castling_possible()
        b.castling = ''.join(f for f in b.castling if f in allowed) or '-'
        if not b._ep_plausible():
            b.ep = '-'
        return b

    def castling_possible(self):
        """
        The castling rights the placement allows ('KQkq' at most): each
        needs its king and that rook still on their starting squares.
        """
        out = ''
        for flag, row, rook_col, king, rook in (('K', 7, 7, 'K', 'R'),
                                                ('Q', 7, 0, 'K', 'R'),
                                                ('k', 0, 7, 'k', 'r'),
                                                ('q', 0, 0, 'k', 'r')):
            if self.board[row][4] == king and self.board[row][rook_col] == rook:
                out += flag
        return out

    def _ep_plausible(self):
        """
        True unless the en-passant square could not come from the pawn
        move just made: that pawn must stand right past it, with the
        square and the one it came from empty.
        """
        if self.ep == '-':
            return True
        c = ord(self.ep[0]) - ord('a')
        r = 8 - int(self.ep[1])
        if self.turn == 'w':         # Black just played a pawn two squares
            return (r == 2 and self.board[3][c] == 'p'
                    and self.board[2][c] == '.' and self.board[1][c] == '.')
        return (r == 5 and self.board[4][c] == 'P'
                and self.board[5][c] == '.' and self.board[6][c] == '.')

    def position_problem(self):
        """
        Why a game cannot start from this position, or None if it can.
        Each side needs exactly one king; pawns cannot stand on the first
        or last rank; a side has at most 16 pieces and 8 pawns; the side
        that just moved cannot be in check, nor give it with more than two
        pieces; and the game must not already be over.
        """
        count = {}
        for row in self.board:
            for p in row:
                if p != '.':
                    count[p] = count.get(p, 0) + 1
        for king, side in (('K', "White"), ('k', "Black")):
            if not count.get(king):
                return f"{side} has no king"
            if count[king] > 1:
                return f"{side} has more than one king"
        if any(p in ('P', 'p') for p in self.board[0] + self.board[7]):
            return "Pawns cannot stand on the first or last rank"
        for white, side in ((True, "White"), (False, "Black")):
            if count.get('P' if white else 'p', 0) > 8:
                return f"{side} has more than 8 pawns"
            if sum(n for p, n in count.items() if p.isupper() == white) > 16:
                return f"{side} has more than 16 pieces"
        waiting = 'b' if self.turn == 'w' else 'w'
        if self.in_check(waiting):
            side = "Black" if waiting == 'b' else "White"
            return f"{side} is in check, so it would have to be {side}'s move"
        kr, kc = self.find_king(self.turn)
        if len(self.attackers(kr, kc, waiting)) > 2:
            return "No move can give check with more than two pieces"
        over, _result, reason, _winner = self.game_result()
        if over:
            return f"The game is already over: {reason[0].lower()}{reason[1:]}"
        return None

    def copy(self):
        """A copy of the position without move history."""
        b = Board.__new__(Board)
        b.board        = [row[:] for row in self.board]
        b.turn         = self.turn
        b.castling     = self.castling
        b.ep           = self.ep
        b.halfmove     = self.halfmove
        b.fullmove     = self.fullmove
        b.move_history = []
        b.pos_history  = {}
        b.cap_white    = []
        b.cap_black    = []
        b._material_cache = None
        return b

    def play_raw(self, uci):
        """
        A new board with *uci* played — unchecked and without history, for
        replaying moves already known to be legal (opening lines, stored
        games). Hundreds of times faster than apply_uci.
        """
        return self._apply_raw(*parse_uci(uci))

    def with_turn(self, side):
        """
        A copy with *side* to move — for asking what that side could do
        if it were its turn ("what does the opponent threaten here?"). The
        en-passant square is dropped: it belonged to the real side to move.
        """
        b = self.copy()
        b.turn = side
        b.ep = '-'
        return b

    # ── Piece helpers ─────────────────────────────────────

    def get(self, r, c):
        return self.board[r][c] if valid(r, c) else None

    def is_w(self, p):  return p not in ('.', '') and p.isupper()
    def is_b(self, p):  return p not in ('.', '') and p.islower()

    def same(self, p1, p2):
        return (self.is_w(p1) and self.is_w(p2)) or (self.is_b(p1) and self.is_b(p2))

    def enemy(self, p, turn):
        return self.is_b(p) if turn == 'w' else self.is_w(p)

    def find_king(self, turn):
        k = 'K' if turn == 'w' else 'k'
        for r in range(8):
            for c in range(8):
                if self.board[r][c] == k:
                    return (r, c)
        return None

    # ── Attack detection ──────────────────────────────────

    def is_attacked(self, r, c, by):
        """Return True if square (r, c) is attacked by side *by*."""
        def has(p):
            return self.is_w(p) if by == 'w' else self.is_b(p)

        # Knights
        for dr, dc in KNIGHT_D:
            nr, nc = r + dr, c + dc
            if valid(nr, nc) and self.board[nr][nc].lower() == 'n' and has(self.board[nr][nc]):
                return True

        # Sliding pieces
        for dirs, chars in [(ROOK_D, 'qr'), (BISHOP_D, 'qb')]:
            for dr, dc in dirs:
                nr, nc = r + dr, c + dc
                while valid(nr, nc):
                    p = self.board[nr][nc]
                    if p != '.':
                        if p.lower() in chars and has(p):
                            return True
                        break
                    nr += dr; nc += dc

        # King
        for dr, dc in KING_D:
            nr, nc = r + dr, c + dc
            if valid(nr, nc) and self.board[nr][nc].lower() == 'k' and has(self.board[nr][nc]):
                return True

        # Pawns
        pawn_dirs = [(1, -1), (1, 1)] if by == 'w' else [(-1, -1), (-1, 1)]
        for dr, dc in pawn_dirs:
            nr, nc = r + dr, c + dc
            if valid(nr, nc) and self.board[nr][nc].lower() == 'p' and has(self.board[nr][nc]):
                return True

        return False

    def in_check(self, turn=None):
        """Return True if *turn*'s king is currently in check."""
        t = turn or self.turn
        k = self.find_king(t)
        if k is None:
            return False
        opp = 'b' if t == 'w' else 'w'
        return self.is_attacked(k[0], k[1], opp)

    # ── Attacker lists and static exchange ────────────────

    @staticmethod
    def _attackers_on(grid, r, c, by):
        """Squares of *by*'s pieces attacking (r, c) on an 8×8 *grid*."""
        def has(p):
            return p != '.' and (p.isupper() if by == 'w' else p.islower())

        out = []
        for dr, dc in KNIGHT_D:
            nr, nc = r + dr, c + dc
            if valid(nr, nc) and grid[nr][nc].lower() == 'n' and has(grid[nr][nc]):
                out.append((nr, nc))
        for dirs, chars in ((ROOK_D, 'qr'), (BISHOP_D, 'qb')):
            for dr, dc in dirs:
                nr, nc = r + dr, c + dc
                while valid(nr, nc):
                    p = grid[nr][nc]
                    if p != '.':
                        if p.lower() in chars and has(p):
                            out.append((nr, nc))
                        break
                    nr += dr; nc += dc
        for dr, dc in KING_D:
            nr, nc = r + dr, c + dc
            if valid(nr, nc) and grid[nr][nc].lower() == 'k' and has(grid[nr][nc]):
                out.append((nr, nc))
        # A white pawn attacks upwards (towards row 0), so it sits one row below
        pr = r + 1 if by == 'w' else r - 1
        for pc in (c - 1, c + 1):
            if valid(pr, pc) and grid[pr][pc].lower() == 'p' and has(grid[pr][pc]):
                out.append((pr, pc))
        return out

    def attackers(self, r, c, by):
        """
        Squares of *by*'s pieces that attack (r, c) right now. Pseudo-legal:
        a pinned piece still counts as an attacker.
        """
        return self._attackers_on(self.board, r, c, by)

    def see(self, r, c, side, first=None):
        """
        Static exchange evaluation on (r, c): the material *side* nets by
        capturing there, both sides then recapturing with their least
        valuable attacker and each free to stop once going on would lose.

        *first* is the square of the piece that makes the opening capture
        (the caller passes a legal one, so pins and checks are respected);
        by default it is *side*'s least valuable attacker. Later recaptures
        are pseudo-legal. Pieces behind a capturer join in as it leaves
        (x-rays), a king only captures onto an undefended square, and a pawn
        capturing onto the last rank is counted as promoting.

        Returns the gain in pawns, never negative — *side* may decline.
        """
        if self.board[r][c] == '.':
            return 0
        grid = [row[:] for row in self.board]
        last_rank = {'w': 0, 'b': 7}

        def pick(by):
            sqs = self._attackers_on(grid, r, c, by)
            if not sqs:
                return None
            sq = min(sqs, key=lambda s: SEE_VALUES[grid[s[0]][s[1]].lower()])
            if grid[sq[0]][sq[1]].lower() == 'k':
                foe = 'b' if by == 'w' else 'w'
                if self._attackers_on(grid, r, c, foe):
                    return None          # the king cannot walk into a defended square
            return sq

        gains = []
        on_square = SEE_VALUES[grid[r][c].lower()]
        mover = side
        sq = first or pick(mover)
        while sq is not None:
            piece = grid[sq[0]][sq[1]]
            value = SEE_VALUES[piece.lower()]
            gain = on_square
            if piece.lower() == 'p' and r == last_rank[mover]:
                gain += SEE_VALUES['q'] - SEE_VALUES['p']
                value = SEE_VALUES['q']
            gains.append(gain - (gains[-1] if gains else 0))
            grid[r][c] = piece
            grid[sq[0]][sq[1]] = '.'
            on_square = value
            mover = 'b' if mover == 'w' else 'w'
            sq = pick(mover)
        if not gains:
            return 0
        # Each side may stop instead of recapturing: fold back from the end
        for i in range(len(gains) - 1, 0, -1):
            gains[i - 1] = -max(-gains[i - 1], gains[i])
        return max(0, gains[0])

    # ── Pseudo-legal move generation ──────────────────────

    def _pseudo(self, r, c):
        """Generate pseudo-legal moves for the piece on (r, c)."""
        piece = self.board[r][c]
        if piece == '.':
            return []
        p    = piece.lower()
        turn = 'w' if piece.isupper() else 'b'
        mv   = []

        if p == 'p':
            fwd     = -1 if turn == 'w' else 1
            start_r = 6  if turn == 'w' else 1
            promo_r = 0  if turn == 'w' else 7
            nr = r + fwd
            # Forward
            if valid(nr, c) and self.board[nr][c] == '.':
                if nr == promo_r:
                    for pp in 'qrbn':
                        mv.append((r, c, nr, c, pp))
                else:
                    mv.append((r, c, nr, c, None))
                    if r == start_r and self.board[r + 2 * fwd][c] == '.':
                        mv.append((r, c, r + 2 * fwd, c, None))
            # Captures
            for dc in [-1, 1]:
                nc = c + dc; nr = r + fwd
                if valid(nr, nc):
                    tgt = self.board[nr][nc]
                    is_cap = self.enemy(tgt, turn)
                    is_ep  = (self.ep != '-' and
                              nr == (8 - int(self.ep[1])) and
                              nc == (ord(self.ep[0]) - ord('a')))
                    if is_cap or is_ep:
                        if nr == promo_r:
                            for pp in 'qrbn':
                                mv.append((r, c, nr, nc, pp))
                        else:
                            mv.append((r, c, nr, nc, None))

        elif p == 'n':
            for dr, dc in KNIGHT_D:
                nr, nc = r + dr, c + dc
                if valid(nr, nc) and not self.same(piece, self.board[nr][nc]):
                    mv.append((r, c, nr, nc, None))

        elif p in ('b', 'r', 'q'):
            dirs = {'b': BISHOP_D, 'r': ROOK_D, 'q': QUEEN_D}[p]
            for dr, dc in dirs:
                nr, nc = r + dr, c + dc
                while valid(nr, nc):
                    t2 = self.board[nr][nc]
                    if t2 == '.':
                        mv.append((r, c, nr, nc, None))
                    elif self.enemy(t2, turn):
                        mv.append((r, c, nr, nc, None)); break
                    else:
                        break
                    nr += dr; nc += dc

        elif p == 'k':
            for dr, dc in KING_D:
                nr, nc = r + dr, c + dc
                if valid(nr, nc) and not self.same(piece, self.board[nr][nc]):
                    mv.append((r, c, nr, nc, None))
            opp = 'b' if turn == 'w' else 'w'
            kr, kc = (7, 4) if turn == 'w' else (0, 4)
            if r == kr and c == kc and not self.is_attacked(kr, kc, opp):
                ks = 'K' if turn == 'w' else 'k'
                qs = 'Q' if turn == 'w' else 'q'
                rp = 'R' if turn == 'w' else 'r'
                cas = self.castling if self.castling else ''
                # Kingside
                if (ks in cas and
                        self.board[kr][5] == '.' and self.board[kr][6] == '.' and
                        self.board[kr][7] == rp and
                        not self.is_attacked(kr, 5, opp) and
                        not self.is_attacked(kr, 6, opp)):
                    mv.append((r, c, kr, kc + 2, None))
                # Queenside
                if (qs in cas and
                        self.board[kr][3] == '.' and self.board[kr][2] == '.' and
                        self.board[kr][1] == '.' and self.board[kr][0] == rp and
                        not self.is_attacked(kr, 3, opp) and
                        not self.is_attacked(kr, 2, opp)):
                    mv.append((r, c, kr, kc - 2, None))
        return mv

    # ── Legal move generation ─────────────────────────────

    def legal_moves(self, turn=None):
        """Return all strictly legal moves for the given side."""
        t = turn or self.turn
        result = []
        for r in range(8):
            for c in range(8):
                p = self.board[r][c]
                if p == '.': continue
                if (t == 'w') != p.isupper(): continue
                for mv in self._pseudo(r, c):
                    b2 = self._apply_raw(*mv)
                    if not b2.in_check(t):
                        result.append(mv)
        return result

    def is_legal(self, uci):
        """True if the UCI move *uci* (a promotion naming its piece) is legal here."""
        try:
            return parse_uci(uci) in self.legal_moves()
        except ValueError:
            return False

    # ── Raw (no-history) move application ─────────────────

    def _apply_raw(self, fr, fc, tr, tc, promo):
        """Apply a move and return a new Board without recording history."""
        b = Board.__new__(Board)
        b.board        = [row[:] for row in self.board]
        b.turn         = self.turn
        b.castling     = self.castling
        b.ep           = self.ep
        b.halfmove     = self.halfmove
        b.fullmove     = self.fullmove
        b.move_history = []
        b.pos_history  = {}
        b.cap_white    = []
        b.cap_black    = []
        b._material_cache = None

        piece  = b.board[fr][fc]
        target = b.board[tr][tc]
        p      = piece.lower()
        turn   = b.turn

        # En-passant capture
        if p == 'p' and b.ep != '-':
            ep_c = ord(b.ep[0]) - ord('a')
            ep_r = 8 - int(b.ep[1])
            if tr == ep_r and tc == ep_c:
                b.board[fr][ep_c] = '.'

        # Castling: move rook
        if p == 'k':
            if fc == 4 and tc == 6:
                b.board[fr][7] = '.'; b.board[fr][5] = 'R' if turn == 'w' else 'r'
            elif fc == 4 and tc == 2:
                b.board[fr][0] = '.'; b.board[fr][3] = 'R' if turn == 'w' else 'r'

        b.board[tr][tc] = piece
        b.board[fr][fc] = '.'

        # Promotion
        if promo:
            b.board[tr][tc] = promo.upper() if turn == 'w' else promo.lower()
        elif p == 'p' and (tr == 0 or tr == 7):
            b.board[tr][tc] = 'Q' if turn == 'w' else 'q'

        # En-passant square for next move
        if p == 'p' and abs(fr - tr) == 2:
            ep_r2 = (fr + tr) // 2
            b.ep = f"{chr(ord('a') + fc)}{8 - ep_r2}"
        else:
            b.ep = '-'

        # Update castling rights
        cas = list((b.castling or '').replace('-', ''))
        if p == 'k':
            remove = 'KQ' if turn == 'w' else 'kq'
            cas = [x for x in cas if x not in remove]
        if p == 'r':
            pairs = [(7, 7, 'K'), (7, 0, 'Q'), (0, 7, 'k'), (0, 0, 'q')]
            for rr, rc, flag in pairs:
                if fr == rr and fc == rc and flag in cas:
                    cas.remove(flag)
        pairs2 = [(7, 7, 'K'), (7, 0, 'Q'), (0, 7, 'k'), (0, 0, 'q')]
        for rr, rc, flag in pairs2:
            if tr == rr and tc == rc and flag in cas:
                cas.remove(flag)
        b.castling = ''.join(cas) if cas else '-'

        b.halfmove = 0 if (p == 'p' or target != '.') else b.halfmove + 1
        if turn == 'b':
            b.fullmove += 1
        b.turn = 'b' if turn == 'w' else 'w'
        return b

    # ── Public move application ───────────────────────────

    def apply_uci(self, uci):
        """
        Apply a UCI-format move, updating all state including history.

        Returns
        -------
        (san, captured_piece)
        """
        fr, fc, tr, tc, promo = parse_uci(uci)

        legal = self.legal_moves()
        if (fr, fc, tr, tc, promo) not in legal:
            if promo is None and (fr, fc, tr, tc, 'q') in legal:
                promo = 'q'
            else:
                raise ValueError(f"Illegal move: {uci!r}")

        san = self._build_san(fr, fc, tr, tc, promo, legal)

        piece  = self.board[fr][fc]
        target = self.board[tr][tc]
        p      = piece.lower()

        ep_removed = None
        if p == 'p' and self.ep != '-':
            ep_c = ord(self.ep[0]) - ord('a')
            ep_r = 8 - int(self.ep[1])
            if tr == ep_r and tc == ep_c:
                ep_removed = self.board[fr][ep_c]

        new = self._apply_raw(fr, fc, tr, tc, promo)
        self.board    = new.board
        self.castling = new.castling
        self.ep       = new.ep
        self.halfmove = new.halfmove
        self.fullmove = new.fullmove
        self.turn     = new.turn
        self._material_cache = None

        in_chk = self.in_check()
        no_mvs = len(self.legal_moves()) == 0
        if in_chk:
            san += '#' if no_mvs else '+'

        cap = ep_removed or (target if target != '.' else None)
        if cap and cap != '.':
            # self.turn has already flipped to the next player,
            # so if it is now Black's turn, White made the capture.
            if self.turn == 'b':
                self.cap_white.append(cap)
            else:
                self.cap_black.append(cap)

        fen_after = self.to_fen()
        self.move_history.append((uci, san, fen_after))
        pos = self._pos_key()
        self.pos_history[pos] = self.pos_history.get(pos, 0) + 1
        return san, cap

    # ── SAN parser ────────────────────────────────────────

    def san_to_uci(self, san):
        """
        Translate a SAN token (``Nbd7``, ``exd8=Q+``, ``O-O``…) into a UCI
        move for the current position, or None if it is not a legal move.

        Only pieces of the named kind that can reach the named square are
        tried, so a game parses in milliseconds — building the SAN of every
        legal move for every token, as matching on SAN text does, is what
        made long PGNs slow to open.
        """
        s = (san or '').strip().rstrip('+#!?').replace('x', '').replace(':', '')
        if s.endswith('e.p.'):
            s = s[:-4]
        if not s or s in ('--', 'Z0'):
            return None
        kr = 7 if self.turn == 'w' else 0
        if s in ('O-O', '0-0', 'O-O-O', '0-0-0'):
            if self.board[kr][4] != ('K' if self.turn == 'w' else 'k'):
                return None
            tc = 6 if s in ('O-O', '0-0') else 2
            cand = [mv for mv in self._pseudo(kr, 4) if mv[3] == tc and mv[2] == kr]
            kind, promo = 'k', None
        else:
            promo = None
            if '=' in s:
                s, promo = s.split('=', 1)
                promo = promo[:1].lower() or None
            elif len(s) >= 3 and s[-1] in 'QRBN' and s[-2].isdigit() and s[0].islower():
                s, promo = s[:-1], s[-1].lower()     # "e8Q" without the "="
            kind = s[0].lower() if s[0] in 'KQRBN' else 'p'
            body = s[1:] if kind != 'p' else s
            if len(body) < 2 or body[-2] not in 'abcdefgh' or not body[-1].isdigit():
                return None
            tc = ord(body[-2]) - ord('a')
            tr = 8 - int(body[-1])
            if not valid(tr, tc):
                return None
            hint = body[:-2]
            hint_file = next((ord(ch) - ord('a') for ch in hint if ch in 'abcdefgh'), None)
            hint_rank = next((8 - int(ch) for ch in hint if ch.isdigit()), None)
            cand = []
            for r in range(8):
                for c in range(8):
                    p = self.board[r][c]
                    if p == '.' or p.lower() != kind:
                        continue
                    if (self.turn == 'w') != p.isupper():
                        continue
                    if hint_file is not None and c != hint_file:
                        continue
                    if hint_rank is not None and r != hint_rank:
                        continue
                    for mv in self._pseudo(r, c):
                        if mv[2] == tr and mv[3] == tc:
                            cand.append(mv)
        for fr, fc, tr2, tc2, pp in cand:
            if pp is None:
                if promo is not None:
                    continue
            elif pp != (promo or 'q'):
                continue
            if self._apply_raw(fr, fc, tr2, tc2, pp).in_check(self.turn):
                continue
            return format_uci(fr, fc, tr2, tc2, pp)
        return None

    # ── SAN builder ───────────────────────────────────────

    def _build_san(self, fr, fc, tr, tc, promo, legal):
        """Build a SAN string for a move (without check/checkmate suffixes)."""
        piece = self.board[fr][fc]; p = piece.lower()
        target = self.board[tr][tc]
        is_cap = (target != '.') or (
            p == 'p' and self.ep != '-' and
            tc == ord(self.ep[0]) - ord('a') and tr == 8 - int(self.ep[1]))

        if p == 'k':
            if fc == 4 and tc == 6: return 'O-O'
            if fc == 4 and tc == 2: return 'O-O-O'

        to_sq = f"{chr(ord('a') + tc)}{8 - tr}"

        if p == 'p':
            san = f"{chr(ord('a') + fc)}x{to_sq}" if is_cap else to_sq
            if promo:
                san += f"={promo.upper()}"
            return san

        pl = p.upper()
        ambig = [m for m in legal
                 if m[2] == tr and m[3] == tc and m[4] == promo
                 and self.board[m[0]][m[1]].lower() == p
                 and not (m[0] == fr and m[1] == fc)]
        dis = ''
        if ambig:
            sf = any(m[1] == fc for m in ambig)
            sr = any(m[0] == fr for m in ambig)
            if not sf:    dis = chr(ord('a') + fc)
            elif not sr:  dis = str(8 - fr)
            else:         dis = f"{chr(ord('a') + fc)}{8 - fr}"

        cap = 'x' if is_cap else ''
        san = f"{pl}{dis}{cap}{to_sq}"
        if promo:
            san += f"={promo.upper()}"
        return san

    # ── Game-result detection ─────────────────────────────

    def game_result(self):
        """
        Check whether the game has ended.

        Returns
        -------
        (over: bool, result: str, reason: str, winner: str | None)
        """
        legal = self.legal_moves()
        if not legal:
            if self.in_check():
                winner = 'black' if self.turn == 'w' else 'white'
                result = '0-1' if self.turn == 'w' else '1-0'
                return True, result, 'Checkmate', winner
            return True, '1/2-1/2', 'Stalemate', None
        if self.halfmove >= 100:
            return True, '1/2-1/2', 'Draw by 50-move rule', None
        pos = self._pos_key()
        if self.pos_history.get(pos, 0) >= 3:
            return True, '1/2-1/2', 'Draw by threefold repetition', None
        if self._insufficient():
            return True, '1/2-1/2', 'Draw by insufficient material', None
        return False, '', '', None

    def can_mate(self, color):
        """
        Return True if *color* could still deliver mate in this position.

        FIDE 6.9: when a player runs out of time the game is drawn, not
        lost, if the opponent "cannot checkmate the player's king by any
        possible series of legal moves". Note *possible*, not *forced* —
        the losing side is allowed to help.

        A bare king can never mate. A king with a single bishop or knight
        cannot mate a bare king either, but it can once the defender has
        anything of its own: a black king on h8 with its own pawn on h7 is
        mated by Kf7 and Ng6. So the single-minor case turns on whether
        the defender has material left to be walled in by.

        Distinct from _insufficient(), which asks whether *neither* side
        can mate and ends the game on the spot. This asks about one side,
        which is the question a flag fall poses.
        """
        mine, theirs = [], []
        for row in self.board:
            for p in row:
                if p == '.' or p.lower() == 'k':
                    continue
                (mine if p.isupper() == (color == 'w') else theirs).append(
                    p.lower())
        if not mine:
            return False
        if len(mine) == 1 and mine[0] in ('b', 'n'):
            return bool(theirs)
        return True

    def _insufficient(self):
        """Return True if the position has insufficient mating material."""
        ws, bs = [], []
        for r in range(8):
            for c in range(8):
                p = self.board[r][c]
                if p == '.': continue
                (ws if p.isupper() else bs).append(p.lower())
        ws = [p for p in ws if p != 'k']
        bs = [p for p in bs if p != 'k']
        if not ws and not bs: return True
        if not ws and bs in [['b'], ['n']]: return True
        if not bs and ws in [['b'], ['n']]: return True
        return False

    # ── Move-history helpers ──────────────────────────────

    def uci_moves_str(self):
        """Return the full move history as a space-separated UCI string."""
        return ' '.join(m[0] for m in self.move_history)

    def uci_moves_list(self):
        """Return the full move history as a list of UCI strings."""
        return [m[0] for m in self.move_history]

    # ── Material counting ─────────────────────────────────

    def material(self):
        """Return (white_material, black_material) centipawn totals."""
        if self._material_cache is not None:
            return self._material_cache
        wm, bm = 0, 0
        for row in self.board:
            for cell in row:
                if cell != '.':
                    v = PIECE_VALUES.get(cell.lower(), 0)
                    if cell.isupper():
                        wm += v
                    else:
                        bm += v
        self._material_cache = (wm, bm)
        return self._material_cache
