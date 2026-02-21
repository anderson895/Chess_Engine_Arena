# ═══════════════════════════════════════════════════════════
#  board.py — Full chess rules engine (Board class)
# ═══════════════════════════════════════════════════════════

from constants import (
    START_FEN, PIECE_VALUES,
    ROOK_D, BISHOP_D, QUEEN_D, KNIGHT_D, KING_D,
)
from utils import valid


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

    def reset(self):
        """Restore the starting position."""
        self.__init__()

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
        if len(uci) < 4:
            raise ValueError(f"Bad UCI: {uci!r}")
        fc = ord(uci[0]) - ord('a'); fr = 8 - int(uci[1])
        tc = ord(uci[2]) - ord('a'); tr = 8 - int(uci[3])
        promo = uci[4].lower() if len(uci) > 4 else None

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
            if self.turn == 'w':
                self.cap_white.append(cap)
            else:
                self.cap_black.append(cap)

        fen_after = self.to_fen()
        self.move_history.append((uci, san, fen_after))
        pos = self._pos_key()
        self.pos_history[pos] = self.pos_history.get(pos, 0) + 1
        return san, cap

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
