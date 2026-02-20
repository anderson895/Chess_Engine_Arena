import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import subprocess
import threading
import time
import queue
import os
import sys
import csv
import sqlite3
from datetime import datetime

# ═══════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

UNICODE = {
    'K': '♔', 'Q': '♕', 'R': '♖', 'B': '♗', 'N': '♘', 'P': '♙',
    'k': '♚', 'q': '♛', 'r': '♜', 'b': '♝', 'n': '♞', 'p': '♟',
}
PIECE_VALUES = {'p':1,'n':3,'b':3,'r':5,'q':9,'k':0}

LIGHT_SQ = "#F0D9B5"
DARK_SQ  = "#B58863"
LAST_FROM= "#CDD26A"
LAST_TO  = "#AAB44F"
CHECK_SQ = "#FF4444"
BG       = "#1A1A2E"
PANEL_BG = "#16213E"
ACCENT   = "#E94560"
TEXT     = "#EAEAEA"
BTN_BG   = "#0F3460"
BTN_HOV  = "#E94560"
LOG_BG   = "#0D0D1A"
INFO_BG  = "#0A0A18"

# ── Move quality colours ──────────────────────────────────
QUALITY_COLORS = {
    "Brilliant": "#1BECA0",
    "Best":      "#5BC0EB",
    "Excellent": "#7FFF00",
    "Great":     "#A8D8A8",
    "Good":      "#FFDD57",
    "Mistake":   "#FFA500",
    "Blunder":   "#FF4444",
}

# ── Rank tiers ────────────────────────────────────────────
RANK_TIERS = [
    (4000, "💀 Super Engine", "#FF0000"),                 # top ultra engine
    (3000, "🌌 Super Grandmaster", "#FF4500"),       # elite engines
    (2800, "👑 Grandmaster", "#FFD700"),             # normal top engines
    (2600, "💎 Master", "#00CFFF"),                  # strong engines
    (2400, "🏆 Expert", "#FF6B35"),                  # above-average engines
    (2200, "⚡ Advanced", "#A0E040"),                # intermediate-strong
    (2000, "🔥 Intermediate", "#FF8C42"),            # mid-level
    (1800, "🤖 Developing", "#C8A2C8"),             # AI/learning engine
    (1600, "🎯 Beginner", "#87CEEB"),                # beginner engines
    (0, "🌱 Novice", "#90EE90"),                     # very low-level
]

ROOK_D   = [(1,0),(-1,0),(0,1),(0,-1)]
BISHOP_D = [(1,1),(1,-1),(-1,1),(-1,-1)]
QUEEN_D  = ROOK_D + BISHOP_D
KNIGHT_D = [(2,1),(2,-1),(-2,1),(-2,-1),(1,2),(1,-2),(-1,2),(-1,-2)]
KING_D   = ROOK_D + BISHOP_D


def valid(r,c): return 0<=r<8 and 0<=c<8


def normalize_engine_name(name):
    """Strip color suffixes so the same engine is always one record."""
    for suffix in [' (White)', ' (Black)', ' (white)', ' (black)',
                   '(White)', '(Black)', '(white)', '(black)']:
        if name.endswith(suffix):
            name = name[:-len(suffix)].strip()
    return name.strip()


def get_db_path():
    home = os.path.expanduser("~")
    db_dir = os.path.join(home, ".chess_arena")
    os.makedirs(db_dir, exist_ok=True)
    return os.path.join(db_dir, "chess_arena.db")


def get_tier(rating):
    for threshold, label, color in RANK_TIERS:
        if rating >= threshold:
            return label, color
    return "🌱 Novice", "#90EE90"


# ── Elo calculation ───────────────────────────────────────

def compute_elo_ratings(games, k=32, start_elo=1500):
    """
    Compute Elo ratings for all engines from game history.
    games: list of (white_engine, black_engine, result) tuples ordered oldest first.
    Returns dict: {engine_name: final_elo}
    """
    ratings = {}

    def get_r(name):
        return ratings.setdefault(normalize_engine_name(name), start_elo)

    def set_r(name, val):
        ratings[normalize_engine_name(name)] = val

    for white, black, result in games:
        w = normalize_engine_name(white)
        b = normalize_engine_name(black)
        rw = get_r(w)
        rb = get_r(b)
        ew = 1 / (1 + 10 ** ((rb - rw) / 400))
        eb = 1 - ew
        if result == '1-0':
            sw, sb = 1.0, 0.0
        elif result == '0-1':
            sw, sb = 0.0, 1.0
        elif result == '1/2-1/2':
            sw, sb = 0.5, 0.5
        else:
            continue  # skip aborted/no result
        set_r(w, rw + k * (sw - ew))
        set_r(b, rb + k * (sb - eb))

    return {n: round(v) for n, v in ratings.items()}


def compute_elo_history(games, engine_name, k=32, start_elo=1500):
    """Return list of (game_index, elo) for a specific engine."""
    ratings = {}
    history = []
    engine_name = normalize_engine_name(engine_name)

    def get_r(name):
        return ratings.setdefault(normalize_engine_name(name), start_elo)

    def set_r(name, val):
        ratings[normalize_engine_name(name)] = val

    for i, (white, black, result) in enumerate(games):
        w = normalize_engine_name(white)
        b = normalize_engine_name(black)
        rw = get_r(w)
        rb = get_r(b)
        ew = 1 / (1 + 10 ** ((rb - rw) / 400))
        eb = 1 - ew
        if result == '1-0':
            sw, sb = 1.0, 0.0
        elif result == '0-1':
            sw, sb = 0.0, 1.0
        elif result == '1/2-1/2':
            sw, sb = 0.5, 0.5
        else:
            continue
        set_r(w, rw + k * (sw - ew))
        set_r(b, rb + k * (sb - eb))
        if w == engine_name or b == engine_name:
            history.append((len(history) + 1, round(get_r(engine_name))))

    return history


# ── Move quality classification ───────────────────────────

def classify_move_quality(cp_before, cp_after, is_white_moving):
    if cp_before is None or cp_after is None:
        return None
    if is_white_moving:
        loss = cp_before - cp_after
    else:
        loss = cp_after - cp_before
    if   loss <= -50:  return "Brilliant"
    elif loss <=   0:  return "Best"
    elif loss <=  10:  return "Excellent"
    elif loss <=  25:  return "Great"
    elif loss <=  50:  return "Good"
    elif loss <= 100:  return "Mistake"
    else:              return "Blunder"


# ═══════════════════════════════════════════════════════════
#  Opening Book  (reads openings_sheet.csv)
# ═══════════════════════════════════════════════════════════

class OpeningBook:
    def __init__(self, csv_path=None):
        self._entries = []
        if csv_path and os.path.isfile(csv_path):
            self._load(csv_path)

    def _load(self, path):
        try:
            with open(path, newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    eco  = (row.get('ECO') or '').strip()
                    name = (row.get('name') or '').strip()
                    raw  = (row.get('moves') or '').strip()
                    if not raw:
                        continue
                    tokens = raw.split()
                    uci_seq = self._tokens_to_uci(tokens)
                    if uci_seq is not None:
                        self._entries.append((tuple(uci_seq), eco, name))
            self._entries.sort(key=lambda x: len(x[0]), reverse=True)
        except Exception as e:
            print(f"[OpeningBook] Failed to load {path}: {e}")

    def _tokens_to_uci(self, tokens):
        board = Board()
        uci_list = []
        for tok in tokens:
            tok = tok.strip()
            if not tok:
                continue
            if self._looks_like_uci(tok):
                try:
                    board.apply_uci(tok)
                    uci_list.append(tok)
                    continue
                except Exception:
                    pass
            uci = self._san_to_uci(board, tok)
            if uci is None:
                return None
            board.apply_uci(uci)
            uci_list.append(uci)
        return uci_list

    @staticmethod
    def _looks_like_uci(tok):
        if len(tok) not in (4, 5):
            return False
        return (tok[0] in 'abcdefgh' and tok[1].isdigit() and
                tok[2] in 'abcdefgh' and tok[3].isdigit())

    @staticmethod
    def _san_to_uci(board, san):
        san_clean = san.replace('+', '').replace('#', '').replace('x', '')
        legal = board.legal_moves()
        for move in legal:
            fr, fc, tr, tc, promo = move
            test_san = board._build_san(fr, fc, tr, tc, promo, legal)
            test_clean = test_san.replace('+','').replace('#','').replace('x','')
            if test_clean == san_clean or test_san == san:
                uci = f"{chr(ord('a')+fc)}{8-fr}{chr(ord('a')+tc)}{8-tr}"
                if promo:
                    uci += promo
                return uci
        return None

    def lookup(self, uci_moves):
        played = tuple(uci_moves)
        for seq, eco, name in self._entries:
            n = len(seq)
            if len(played) >= n and played[:n] == seq:
                return eco, name
        return None, None

    @property
    def loaded(self):
        return len(self._entries) > 0


# ═══════════════════════════════════════════════════════════
#  Board — full rules
# ═══════════════════════════════════════════════════════════

class Board:
    def __init__(self):
        self.board        = None
        self.turn         = 'w'
        self.castling     = 'KQkq'
        self.ep           = '-'
        self.halfmove     = 0
        self.fullmove     = 1
        self.move_history = []
        self.pos_history  = {}
        self.cap_white    = []
        self.cap_black    = []
        self._material_cache = None
        self._load_fen(START_FEN)

    def reset(self):
        self.__init__()

    def _load_fen(self, fen):
        parts = fen.split()
        self.board = []
        for row_str in parts[0].split('/'):
            row = []
            for ch in row_str:
                if ch.isdigit(): row.extend(['.']*int(ch))
                else:            row.append(ch)
            self.board.append(row)
        self.turn     = parts[1] if len(parts)>1 else 'w'
        self.castling = parts[2] if len(parts)>2 else '-'
        self.ep       = parts[3] if len(parts)>3 else '-'
        self.halfmove = int(parts[4]) if len(parts)>4 else 0
        self.fullmove = int(parts[5]) if len(parts)>5 else 1
        self._material_cache = None

    def to_fen(self):
        rows=[]
        for row in self.board:
            e=0; s=''
            for cell in row:
                if cell=='.': e+=1
                else:
                    if e: s+=str(e); e=0
                    s+=cell
            if e: s+=str(e)
            rows.append(s)
        c = self.castling if self.castling else '-'
        return f"{'/'.join(rows)} {self.turn} {c} {self.ep} {self.halfmove} {self.fullmove}"

    def _pos_key(self):
        parts = self.to_fen().split()
        return ' '.join(parts[:4])

    def get(self, r, c):
        return self.board[r][c] if valid(r,c) else None

    def is_w(self, p): return p not in ('.','') and p.isupper()
    def is_b(self, p): return p not in ('.','') and p.islower()
    def same(self, p1, p2):
        return (self.is_w(p1) and self.is_w(p2)) or (self.is_b(p1) and self.is_b(p2))
    def enemy(self, p, turn):
        return self.is_b(p) if turn=='w' else self.is_w(p)

    def find_king(self, turn):
        k = 'K' if turn=='w' else 'k'
        for r in range(8):
            for c in range(8):
                if self.board[r][c]==k: return (r,c)
        return None

    def is_attacked(self, r, c, by):
        def has(p): return (self.is_w(p) if by=='w' else self.is_b(p))
        for dr,dc in KNIGHT_D:
            nr,nc=r+dr,c+dc
            if valid(nr,nc) and self.board[nr][nc].lower()=='n' and has(self.board[nr][nc]):
                return True
        for dirs,chars in [(ROOK_D,'qr'),(BISHOP_D,'qb')]:
            for dr,dc in dirs:
                nr,nc=r+dr,c+dc
                while valid(nr,nc):
                    p=self.board[nr][nc]
                    if p!='.':
                        if p.lower() in chars and has(p): return True
                        break
                    nr+=dr; nc+=dc
        for dr,dc in KING_D:
            nr,nc=r+dr,c+dc
            if valid(nr,nc) and self.board[nr][nc].lower()=='k' and has(self.board[nr][nc]):
                return True
        pawn_dirs = [(1,-1),(1,1)] if by=='w' else [(-1,-1),(-1,1)]
        for dr,dc in pawn_dirs:
            nr,nc=r+dr,c+dc
            if valid(nr,nc) and self.board[nr][nc].lower()=='p' and has(self.board[nr][nc]):
                return True
        return False

    def in_check(self, turn=None):
        t = turn or self.turn
        k = self.find_king(t)
        if k is None: return False
        opp = 'b' if t=='w' else 'w'
        return self.is_attacked(k[0], k[1], opp)

    def _pseudo(self, r, c):
        piece = self.board[r][c]
        if piece=='.': return []
        p    = piece.lower()
        turn = 'w' if piece.isupper() else 'b'
        mv   = []

        if p=='p':
            fwd = -1 if turn=='w' else 1
            start_r = 6 if turn=='w' else 1
            promo_r = 0 if turn=='w' else 7
            nr=r+fwd
            if valid(nr,c) and self.board[nr][c]=='.':
                if nr==promo_r:
                    for pp in 'qrbn': mv.append((r,c,nr,c,pp))
                else:
                    mv.append((r,c,nr,c,None))
                    if r==start_r and self.board[r+2*fwd][c]=='.':
                        mv.append((r,c,r+2*fwd,c,None))
            for dc in [-1,1]:
                nc=c+dc; nr=r+fwd
                if valid(nr,nc):
                    tgt=self.board[nr][nc]
                    is_cap = self.enemy(tgt,turn)
                    is_ep  = (self.ep!='-' and
                               nr==(8-int(self.ep[1])) and
                               nc==(ord(self.ep[0])-ord('a')))
                    if is_cap or is_ep:
                        if nr==promo_r:
                            for pp in 'qrbn': mv.append((r,c,nr,nc,pp))
                        else:
                            mv.append((r,c,nr,nc,None))

        elif p=='n':
            for dr,dc in KNIGHT_D:
                nr,nc=r+dr,c+dc
                if valid(nr,nc) and not self.same(piece,self.board[nr][nc]):
                    mv.append((r,c,nr,nc,None))

        elif p in ('b','r','q'):
            dirs={'b':BISHOP_D,'r':ROOK_D,'q':QUEEN_D}[p]
            for dr,dc in dirs:
                nr,nc=r+dr,c+dc
                while valid(nr,nc):
                    t2=self.board[nr][nc]
                    if t2=='.': mv.append((r,c,nr,nc,None))
                    elif self.enemy(t2,turn): mv.append((r,c,nr,nc,None)); break
                    else: break
                    nr+=dr; nc+=dc

        elif p=='k':
            for dr,dc in KING_D:
                nr,nc=r+dr,c+dc
                if valid(nr,nc) and not self.same(piece,self.board[nr][nc]):
                    mv.append((r,c,nr,nc,None))
            opp='b' if turn=='w' else 'w'
            kr,kc=(7,4) if turn=='w' else (0,4)
            if r==kr and c==kc and not self.is_attacked(kr,kc,opp):
                ks = 'K' if turn=='w' else 'k'
                qs = 'Q' if turn=='w' else 'q'
                rp = 'R' if turn=='w' else 'r'
                cas = self.castling if self.castling else ''
                if (ks in cas and
                        self.board[kr][5]=='.' and self.board[kr][6]=='.' and
                        self.board[kr][7]==rp and
                        not self.is_attacked(kr,5,opp) and not self.is_attacked(kr,6,opp)):
                    mv.append((r,c,kr,kc+2,None))
                if (qs in cas and
                        self.board[kr][3]=='.' and self.board[kr][2]=='.' and
                        self.board[kr][1]=='.' and self.board[kr][0]==rp and
                        not self.is_attacked(kr,3,opp) and not self.is_attacked(kr,2,opp)):
                    mv.append((r,c,kr,kc-2,None))
        return mv

    def legal_moves(self, turn=None):
        t = turn or self.turn
        result=[]
        for r in range(8):
            for c in range(8):
                p=self.board[r][c]
                if p=='.': continue
                if (t=='w')!=p.isupper(): continue
                for mv in self._pseudo(r,c):
                    b2=self._apply_raw(*mv)
                    if not b2.in_check(t):
                        result.append(mv)
        return result

    def _apply_raw(self, fr, fc, tr, tc, promo):
        b = Board.__new__(Board)
        b.board       = [row[:] for row in self.board]
        b.turn        = self.turn
        b.castling    = self.castling
        b.ep          = self.ep
        b.halfmove    = self.halfmove
        b.fullmove    = self.fullmove
        b.move_history= []
        b.pos_history = {}
        b.cap_white   = []
        b.cap_black   = []
        b._material_cache = None

        piece  = b.board[fr][fc]
        target = b.board[tr][tc]
        p      = piece.lower()
        turn   = b.turn

        if p=='p' and b.ep!='-':
            ep_c=ord(b.ep[0])-ord('a')
            ep_r=8-int(b.ep[1])
            if tr==ep_r and tc==ep_c:
                b.board[fr][ep_c]='.'

        if p=='k':
            if fc==4 and tc==6:
                b.board[fr][7]='.'; b.board[fr][5]='R' if turn=='w' else 'r'
            elif fc==4 and tc==2:
                b.board[fr][0]='.'; b.board[fr][3]='R' if turn=='w' else 'r'

        b.board[tr][tc]=piece
        b.board[fr][fc]='.'

        if promo:
            b.board[tr][tc]=promo.upper() if turn=='w' else promo.lower()
        elif p=='p' and (tr==0 or tr==7):
            b.board[tr][tc]='Q' if turn=='w' else 'q'

        if p=='p' and abs(fr-tr)==2:
            ep_r2=(fr+tr)//2
            b.ep=f"{chr(ord('a')+fc)}{8-ep_r2}"
        else:
            b.ep='-'

        cas=list((b.castling or '').replace('-',''))
        if p=='k':
            remove='KQ' if turn=='w' else 'kq'
            cas=[x for x in cas if x not in remove]
        if p=='r':
            pairs=[(7,7,'K'),(7,0,'Q'),(0,7,'k'),(0,0,'q')]
            for rr,rc,flag in pairs:
                if fr==rr and fc==rc and flag in cas: cas.remove(flag)
        pairs2=[(7,7,'K'),(7,0,'Q'),(0,7,'k'),(0,0,'q')]
        for rr,rc,flag in pairs2:
            if tr==rr and tc==rc and flag in cas: cas.remove(flag)
        b.castling=''.join(cas) if cas else '-'

        b.halfmove = 0 if (p=='p' or target!='.') else b.halfmove+1
        if turn=='b': b.fullmove+=1
        b.turn='b' if turn=='w' else 'w'
        return b

    def apply_uci(self, uci):
        if len(uci)<4:
            raise ValueError(f"Bad UCI: {uci!r}")
        fc=ord(uci[0])-ord('a'); fr=8-int(uci[1])
        tc=ord(uci[2])-ord('a'); tr=8-int(uci[3])
        promo=uci[4].lower() if len(uci)>4 else None

        legal=self.legal_moves()

        if (fr,fc,tr,tc,promo) not in legal:
            if promo is None and (fr,fc,tr,tc,'q') in legal:
                promo='q'
            else:
                raise ValueError(f"Illegal move: {uci!r}")

        san=self._build_san(fr,fc,tr,tc,promo,legal)

        piece  = self.board[fr][fc]
        target = self.board[tr][tc]
        p      = piece.lower()

        ep_removed=None
        if p=='p' and self.ep!='-':
            ep_c=ord(self.ep[0])-ord('a')
            ep_r=8-int(self.ep[1])
            if tr==ep_r and tc==ep_c:
                ep_removed=self.board[fr][ep_c]

        new=self._apply_raw(fr,fc,tr,tc,promo)
        self.board    =new.board
        self.castling =new.castling
        self.ep       =new.ep
        self.halfmove =new.halfmove
        self.fullmove =new.fullmove
        self.turn     =new.turn
        self._material_cache = None

        in_chk=self.in_check()
        no_mvs=len(self.legal_moves())==0
        if in_chk:
            san += '#' if no_mvs else '+'

        cap = ep_removed or (target if target!='.' else None)
        if cap and cap!='.':
            if self.turn=='w':
                self.cap_white.append(cap)
            else:
                self.cap_black.append(cap)

        fen_after=self.to_fen()
        self.move_history.append((uci,san,fen_after))
        pos=self._pos_key()
        self.pos_history[pos]=self.pos_history.get(pos,0)+1
        return san, cap

    def _build_san(self, fr, fc, tr, tc, promo, legal):
        piece=self.board[fr][fc]; p=piece.lower()
        target=self.board[tr][tc]
        is_cap=(target!='.') or (
            p=='p' and self.ep!='-' and
            tc==ord(self.ep[0])-ord('a') and tr==8-int(self.ep[1]))

        if p=='k':
            if fc==4 and tc==6: return 'O-O'
            if fc==4 and tc==2: return 'O-O-O'

        to_sq=f"{chr(ord('a')+tc)}{8-tr}"

        if p=='p':
            san=(f"{chr(ord('a')+fc)}x{to_sq}" if is_cap else to_sq)
            if promo: san+=f"={promo.upper()}"
            return san

        pl=p.upper()
        ambig=[m for m in legal
               if m[2]==tr and m[3]==tc and m[4]==promo
               and self.board[m[0]][m[1]].lower()==p
               and not(m[0]==fr and m[1]==fc)]
        dis=''
        if ambig:
            sf=any(m[1]==fc for m in ambig)
            sr=any(m[0]==fr for m in ambig)
            if not sf:    dis=chr(ord('a')+fc)
            elif not sr:  dis=str(8-fr)
            else:         dis=f"{chr(ord('a')+fc)}{8-fr}"

        cap='x' if is_cap else ''
        san=f"{pl}{dis}{cap}{to_sq}"
        if promo: san+=f"={promo.upper()}"
        return san

    def game_result(self):
        legal=self.legal_moves()
        if not legal:
            if self.in_check():
                winner = 'black' if self.turn == 'w' else 'white'
                result = '0-1' if self.turn == 'w' else '1-0'
                return True, result, 'Checkmate', winner
            return True, '1/2-1/2', 'Stalemate', None
        if self.halfmove>=100:
            return True, '1/2-1/2', 'Draw by 50-move rule', None
        pos=self._pos_key()
        if self.pos_history.get(pos,0)>=3:
            return True, '1/2-1/2', 'Draw by threefold repetition', None
        if self._insufficient():
            return True, '1/2-1/2', 'Draw by insufficient material', None
        return False, '', '', None

    def _insufficient(self):
        ws,bs=[],[]
        for r in range(8):
            for c in range(8):
                p=self.board[r][c]
                if p=='.': continue
                (ws if p.isupper() else bs).append(p.lower())
        ws=[p for p in ws if p!='k']
        bs=[p for p in bs if p!='k']
        if not ws and not bs: return True
        if not ws and bs in [['b'],['n']]: return True
        if not bs and ws in [['b'],['n']]: return True
        return False

    def uci_moves_str(self):
        return ' '.join(m[0] for m in self.move_history)

    def uci_moves_list(self):
        return [m[0] for m in self.move_history]

    def material(self):
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


# ═══════════════════════════════════════════════════════════
#  UCI Engine
# ═══════════════════════════════════════════════════════════

class UCIEngine:
    def __init__(self, path, name="Engine"):
        self.path    = path
        self.name    = name
        self.process = None
        self.ready   = False
        self.q       = queue.Queue()
        self.last_info = {}

    def start(self):
        kw = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                  stderr=subprocess.DEVNULL, universal_newlines=True, bufsize=1)
        if sys.platform=='win32':
            kw['creationflags']=subprocess.CREATE_NO_WINDOW
        try:
            self.process=subprocess.Popen([self.path], **kw)
        except FileNotFoundError:
            raise RuntimeError(f"Engine not found: {self.path}")
        except PermissionError:
            raise RuntimeError(f"Permission denied: {self.path}")
        threading.Thread(target=self._reader, daemon=True).start()
        self._send("uci")
        if not self._wait("uciok", 15):
            raise RuntimeError(f"No 'uciok' from {self.path}")
        self.ready=True
        self._send("isready")
        if not self._wait("readyok", 10):
            raise RuntimeError(f"No 'readyok' from {self.path}")

    def _reader(self):
        try:
            for line in self.process.stdout:
                self.q.put(line.rstrip('\n'))
        except Exception:
            pass

    def _send(self, cmd):
        if self.process and self.process.poll() is None:
            try:
                self.process.stdin.write(cmd+'\n')
                self.process.stdin.flush()
            except BrokenPipeError:
                pass

    def _drain(self):
        while not self.q.empty():
            try: self.q.get_nowait()
            except queue.Empty: break

    def _wait(self, kw, timeout):
        end=time.time()+timeout
        while time.time()<end:
            try:
                line=self.q.get(timeout=0.2)
                if not line:
                    continue
                if line.strip()==kw or line.startswith(kw): return True
            except queue.Empty:
                if self.process and self.process.poll() is not None:
                    return False
        return False

    def get_best_move(self, moves_str, movetime_ms=1000, on_info=None):
        if not self.ready or not self.alive:
            return None
        self._drain()
        self.last_info={}
        cmd = f"position startpos moves {moves_str}" if moves_str else "position startpos"
        self._send(cmd)
        self._send(f"go movetime {movetime_ms}")

        max_wait = (movetime_ms / 1000) + 10
        end = time.time() + max_wait
        best = None

        while time.time() < end:
            try:
                line=self.q.get(timeout=0.3)
            except queue.Empty:
                if self.process and self.process.poll() is not None:
                    break
                continue
            if not line:
                continue
            if line.startswith('info '):
                info=self._parse_info(line)
                self.last_info.update(info)
                if on_info: on_info(info)
            elif line.startswith('bestmove'):
                parts=line.split()
                if len(parts)>1 and parts[1] not in ('(none)','null','0000'):
                    best=parts[1]
                break
        return best

    def get_eval(self, moves_str, movetime_ms=200):
        if not self.ready or not self.alive:
            return None
        self._drain()
        cmd = f"position startpos moves {moves_str}" if moves_str else "position startpos"
        self._send(cmd)
        self._send(f"go movetime {movetime_ms}")

        end = time.time() + movetime_ms / 1000 + 5
        last_score = None
        last_score_type = 'cp'

        while time.time() < end:
            try:
                line = self.q.get(timeout=0.2)
            except queue.Empty:
                if self.process and self.process.poll() is not None:
                    break
                continue
            if not line:
                continue
            if line.startswith('info '):
                info = self._parse_info(line)
                if 'score' in info:
                    last_score = info['score']
                    last_score_type = info.get('score_type', 'cp')
            elif line.startswith('bestmove'):
                break

        if last_score is None:
            return None
        if last_score_type == 'mate':
            return 30000 if last_score > 0 else -30000
        return last_score

    def _parse_info(self, line):
        info={}; tokens=line.split()[1:]; i=0
        while i<len(tokens):
            t=tokens[i]
            if t=='depth' and i+1<len(tokens):
                try: info['depth']=int(tokens[i+1]); i+=2; continue
                except ValueError: pass
            elif t=='score' and i+1<len(tokens):
                st=tokens[i+1]
                if st in ('cp','mate') and i+2<len(tokens):
                    try:
                        info['score']=int(tokens[i+2])
                        info['score_type']=st; i+=3; continue
                    except ValueError: pass
            elif t=='nodes' and i+1<len(tokens):
                try: info['nodes']=int(tokens[i+1]); i+=2; continue
                except ValueError: pass
            elif t=='nps' and i+1<len(tokens):
                try: info['nps']=int(tokens[i+1]); i+=2; continue
                except ValueError: pass
            elif t=='pv':
                info['pv']=tokens[i+1:i+6]; break
            i+=1
        return info

    def stop(self):
        if self.process:
            try:
                self._send("stop"); time.sleep(0.1)
                self._send("quit")
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                pass
            self.process=None; self.ready=False

    @property
    def alive(self):
        return self.process is not None and self.process.poll() is None


# ═══════════════════════════════════════════════════════════
#  Analyzer Engine (Stockfish) — separate instance for eval
# ═══════════════════════════════════════════════════════════

class AnalyzerEngine(UCIEngine):
    """A dedicated engine instance for position evaluation / move quality."""

    def eval_position(self, moves_str, movetime_ms=150):
        if not self.ready or not self.alive:
            return None, None
        self._drain()
        cmd = f"position startpos moves {moves_str}" if moves_str else "position startpos"
        self._send(cmd)
        self._send(f"go movetime {movetime_ms}")

        end = time.time() + movetime_ms / 1000 + 5
        last_score = None
        last_score_type = 'cp'
        n_moves = len(moves_str.split()) if moves_str else 0
        side_to_move = 'w' if n_moves % 2 == 0 else 'b'

        while time.time() < end:
            try:
                line = self.q.get(timeout=0.2)
            except queue.Empty:
                if self.process and self.process.poll() is not None:
                    break
                continue
            if not line:
                continue
            if line.startswith('info '):
                info = self._parse_info(line)
                if 'score' in info:
                    last_score = info['score']
                    last_score_type = info.get('score_type', 'cp')
            elif line.startswith('bestmove'):
                break

        if last_score is None:
            return None, None

        if last_score_type == 'mate':
            cp = 30000 if last_score > 0 else -30000
        else:
            cp = last_score

        if side_to_move == 'b':
            cp = -cp

        return cp, last_score_type


# ═══════════════════════════════════════════════════════════
#  PGN
# ═══════════════════════════════════════════════════════════

def build_pgn(white, black, moves, result, date, opening_name=None):
    opening_tag = f'[Opening "{opening_name}"]\n' if opening_name else ''
    hdr = (f'[Event "Engine Match"]\n[Site "Chess Engine Arena"]\n'
           f'[Date "{date}"]\n[Round "1"]\n[White "{white}"]\n'
           f'[Black "{black}"]\n[Result "{result}"]\n{opening_tag}\n')
    body=''; sans=[m[1] for m in moves]
    for i,san in enumerate(sans):
        if i%2==0: body+=f"{i//2+1}. "
        body+=san+' '
        if (i+1)%10==0: body+='\n'
    return hdr+body+result


# ═══════════════════════════════════════════════════════════
#  Promotion Dialog
# ═══════════════════════════════════════════════════════════

def ask_promotion(root, color):
    result = [None]
    dialog = tk.Toplevel(root)
    dialog.title("Promote Pawn")
    dialog.configure(bg=BG)
    dialog.resizable(False, False)
    dialog.transient(root)
    dialog.grab_set()

    w, h = 340, 140
    x = (dialog.winfo_screenwidth() // 2) - (w // 2)
    y = (dialog.winfo_screenheight() // 2) - (h // 2)
    dialog.geometry(f'{w}x{h}+{x}+{y}')

    tk.Label(dialog, text="Choose promotion piece:", bg=BG, fg=TEXT,
             font=('Segoe UI', 12, 'bold')).pack(pady=(15, 10))

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.pack()

    pieces = [('q', '♕' if color == 'w' else '♛', 'Queen'),
              ('r', '♖' if color == 'w' else '♜', 'Rook'),
              ('b', '♗' if color == 'w' else '♝', 'Bishop'),
              ('n', '♘' if color == 'w' else '♞', 'Knight')]

    def choose(p):
        result[0] = p
        dialog.destroy()

    for piece_char, symbol, name in pieces:
        f = tk.Frame(btn_frame, bg=BG)
        f.pack(side='left', padx=8)
        btn = tk.Button(f, text=symbol, command=lambda p=piece_char: choose(p),
                        bg=BTN_BG, fg='#FFD700' if color == 'w' else '#CCCCCC',
                        font=('Segoe UI', 24), width=2, relief='flat',
                        cursor='hand2', activebackground=ACCENT)
        btn.pack()
        tk.Label(f, text=name, bg=BG, fg="#888", font=('Segoe UI', 8)).pack()

    dialog.protocol("WM_DELETE_WINDOW", lambda: choose('q'))
    root.wait_window(dialog)
    return result[0] or 'q'


# ═══════════════════════════════════════════════════════════
#  Stop Game — Result Entry Dialog
# ═══════════════════════════════════════════════════════════

def ask_stop_result(root, white_name, black_name):
    result_val = [None]
    reason_val = [None]

    dialog = tk.Toplevel(root)
    dialog.title("⏹  Stop Game — Enter Result")
    dialog.configure(bg=BG)
    dialog.resizable(True, True)
    dialog.transient(root)
    dialog.grab_set()

    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    w  = min(600, sw - 80)
    h  = min(500, sh - 100)
    h  = max(h, 480)
    x  = (sw - w) // 2
    y  = (sh - h) // 2
    dialog.geometry(f'{w}x{h}+{x}+{y}')
    dialog.minsize(480, 420)

    chosen_result = tk.StringVar(value="")
    chosen_reason = tk.StringVar(value="")

    hdr = tk.Frame(dialog, bg=BG)
    hdr.pack(fill='x', padx=24, pady=(20, 0))
    tk.Label(hdr, text="⏹  STOP GAME", bg=BG, fg=ACCENT,
             font=('Segoe UI', 17, 'bold')).pack(anchor='w')
    tk.Frame(dialog, bg=ACCENT, height=2).pack(fill='x', padx=24, pady=(8, 12))
    tk.Label(dialog, text="Select the result to record before stopping:",
             bg=BG, fg=TEXT, font=('Segoe UI', 11)).pack(anchor='w', padx=24, pady=(0, 10))

    btn_area = tk.Frame(dialog, bg=BG)
    btn_area.pack(fill='x', padx=24)

    RESULTS = [
        ("1-0",     f"⬜  {normalize_engine_name(white_name)} wins  (White)", "#FFD700"),
        ("0-1",     f"⬛  {normalize_engine_name(black_name)} wins  (Black)", "#C8C8C8"),
        ("1/2-1/2", "½ - ½   Draw",                                            "#00BFFF"),
        ("*",       "✕   No result / Abort",                                   "#777777"),
    ]

    result_btns = {}
    for res, label, color in RESULTS:
        b = tk.Button(
            btn_area, text=label,
            command=lambda r=res: _pick(r),
            bg=BTN_BG, fg=color,
            activebackground=ACCENT, activeforeground='white',
            relief='flat', font=('Segoe UI', 11, 'bold'),
            padx=14, pady=10, cursor='hand2', anchor='w',
            highlightthickness=2, highlightbackground=BTN_BG)
        b.pack(fill='x', pady=3)
        result_btns[res] = b

    def _pick(res):
        chosen_result.set(res)
        for r2, b2 in result_btns.items():
            _, _, col = RESULTS[next(i for i, (rv, _, _) in enumerate(RESULTS) if rv == r2)]
            if r2 == res:
                b2.config(bg=ACCENT, highlightbackground=ACCENT, fg='white')
            else:
                b2.config(bg=BTN_BG, highlightbackground=BTN_BG, fg=col)
        _update_reasons(res)
        confirm_btn.config(state='normal')

    REASON_OPTIONS = {
        "1-0": ["White wins","White wins on time","Black resigned","Black forfeits","Illegal move by Black"],
        "0-1": ["Black wins","Black wins on time","White resigned","White forfeits","Illegal move by White"],
        "1/2-1/2": ["Draw by agreement","Stalemate","Draw by repetition","Draw by 50-move rule","Draw by insufficient material"],
        "*": ["Game aborted","No result","Stopped by user"],
    }

    tk.Label(dialog, text="Reason:", bg=BG, fg="#AAA",
             font=('Segoe UI', 10)).pack(anchor='w', padx=24, pady=(14, 3))

    reason_combo = ttk.Combobox(
        dialog, textvariable=chosen_reason,
        font=('Segoe UI', 10), state='disabled',
        values=[], height=8)
    reason_combo.pack(fill='x', padx=24, ipady=4)

    def _update_reasons(res):
        opts = REASON_OPTIONS.get(res, ["Stopped by user"])
        reason_combo.config(values=opts, state='readonly')
        chosen_reason.set(opts[0])

    foot = tk.Frame(dialog, bg=BG)
    foot.pack(side='bottom', fill='x', padx=24, pady=18)

    def _confirm():
        r = chosen_result.get()
        if not r:
            messagebox.showwarning("No Result", "Please select a result first.", parent=dialog)
            return
        reason_text = chosen_reason.get().strip() or "Stopped by user"
        result_val[0] = r
        reason_val[0] = reason_text
        dialog.destroy()

    def _cancel():
        dialog.destroy()

    confirm_btn = tk.Button(
        foot, text="✔  Confirm & Stop", command=_confirm,
        bg=ACCENT, fg='white', activebackground=BTN_HOV,
        relief='flat', font=('Segoe UI', 12, 'bold'),
        padx=16, pady=10, cursor='hand2', state='disabled')
    confirm_btn.pack(side='left', expand=True, fill='x', padx=(0, 8))

    cancel_btn = tk.Button(
        foot, text="✕  Cancel", command=_cancel,
        bg=BTN_BG, fg=TEXT, activebackground=BTN_HOV,
        relief='flat', font=('Segoe UI', 12),
        padx=16, pady=10, cursor='hand2')
    cancel_btn.pack(side='left', expand=True, fill='x')

    dialog.bind('<Escape>', lambda e: _cancel())
    root.wait_window(dialog)
    return result_val[0], reason_val[0]


# ═══════════════════════════════════════════════════════════
#  Search Bar helper widget
# ═══════════════════════════════════════════════════════════

def make_search_bar(parent, on_search_cb, placeholder="🔍 Search…"):
    frame = tk.Frame(parent, bg=PANEL_BG)
    var = tk.StringVar()

    tk.Label(frame, text="🔍", bg=PANEL_BG, fg=ACCENT,
             font=('Segoe UI', 11)).pack(side='left', padx=(8, 2))

    entry = tk.Entry(frame, textvariable=var, bg=LOG_BG, fg=TEXT,
                     insertbackground=TEXT, font=('Segoe UI', 10),
                     relief='flat', highlightthickness=1,
                     highlightcolor=ACCENT, highlightbackground='#333')
    entry.pack(side='left', fill='x', expand=True, ipady=5, padx=(0, 4))

    entry.insert(0, placeholder)
    entry.config(fg='#666')

    def on_focus_in(e):
        if entry.get() == placeholder:
            entry.delete(0, 'end')
            entry.config(fg=TEXT)

    def on_focus_out(e):
        if not entry.get():
            entry.insert(0, placeholder)
            entry.config(fg='#666')

    entry.bind('<FocusIn>', on_focus_in)
    entry.bind('<FocusOut>', on_focus_out)

    def clear_search():
        entry.delete(0, 'end')
        entry.insert(0, placeholder)
        entry.config(fg='#666')
        on_search_cb('')

    clear_btn = tk.Button(frame, text='✕', command=clear_search,
                          bg=PANEL_BG, fg='#666', relief='flat',
                          font=('Segoe UI', 9), cursor='hand2',
                          activebackground=PANEL_BG, activeforeground=ACCENT,
                          padx=4)
    clear_btn.pack(side='left', padx=(0, 4))

    def _on_var_change(*_):
        val = var.get()
        if val == placeholder:
            on_search_cb('')
        else:
            on_search_cb(val)

    var.trace_add('write', _on_var_change)
    return frame, var


# ═══════════════════════════════════════════════════════════
#  Loading Screen
# ═══════════════════════════════════════════════════════════

class LoadingScreen:
    def __init__(self, root):
        self.root = root
        self.root.title("♟  Chess Engine Arena — Starting…")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)

        w, h = 520, 360
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        self._openings_done  = False
        self._analyzer_done  = False
        self._opening_book   = None
        self._opening_path   = None
        self._analyzer_path  = None
        self._analyzer_eng   = None

        self._build()
        self._start_loading()

    def _build(self):
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill='both', expand=True, padx=40, pady=30)

        tk.Label(outer, text="♟", bg=BG, fg=ACCENT,
                 font=('Segoe UI', 60)).pack(pady=(0, 2))

        tk.Label(outer, text="Chess Engine Arena", bg=BG, fg=TEXT,
                 font=('Segoe UI', 22, 'bold')).pack()

        tk.Frame(outer, bg=ACCENT, height=2).pack(fill='x', pady=(12, 20))

        row1 = tk.Frame(outer, bg=BG)
        row1.pack(fill='x', pady=(0, 10))
        tk.Label(row1, text="📖  Openings CSV", bg=BG, fg="#AAA",
                 font=('Segoe UI', 10), width=20, anchor='w').pack(side='left')
        self._open_bar = ttk.Progressbar(row1, maximum=100, length=200, mode='indeterminate')
        self._open_bar.pack(side='left', padx=(8, 8))
        self._open_lbl = tk.Label(row1, text="Loading…", bg=BG, fg="#666",
                                   font=('Consolas', 9), width=16, anchor='w')
        self._open_lbl.pack(side='left')

        row2 = tk.Frame(outer, bg=BG)
        row2.pack(fill='x', pady=(0, 10))
        tk.Label(row2, text="🔍  Analyzer Engine", bg=BG, fg="#AAA",
                 font=('Segoe UI', 10), width=20, anchor='w').pack(side='left')
        self._anal_bar = ttk.Progressbar(row2, maximum=100, length=200, mode='indeterminate')
        self._anal_bar.pack(side='left', padx=(8, 8))
        self._anal_lbl = tk.Label(row2, text="Loading…", bg=BG, fg="#666",
                                   font=('Consolas', 9), width=16, anchor='w')
        self._anal_lbl.pack(side='left')

        self._status_var = tk.StringVar(value="Initialising…")
        tk.Label(outer, textvariable=self._status_var, bg=BG, fg="#555",
                 font=('Segoe UI', 9), anchor='center').pack(pady=(16, 0))

        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TProgressbar', troughcolor=LOG_BG, background=ACCENT, thickness=14)

        self._open_bar.start(12)
        self._anal_bar.start(12)

    def _start_loading(self):
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
        except NameError:
            script_dir = os.getcwd()
        cwd = os.getcwd()

        csv_candidates = []
        for base in [cwd, script_dir]:
            for sub in ["opening", "openings", ""]:
                for fname in ["openings_sheet.csv", "openings.csv"]:
                    p = os.path.join(base, sub, fname) if sub else os.path.join(base, fname)
                    csv_candidates.append(p)

        anal_candidates = []
        for base in [script_dir, cwd]:
            for sub in ["analyzer", "stockfish", "engine", "."]:
                for exe in ["stockfish_18_x86-64.exe", "stockfish.exe",
                            "stockfish_x86-64.exe", "stockfish"]:
                    anal_candidates.append(os.path.join(base, sub, exe))

        threading.Thread(target=self._load_openings, args=(csv_candidates,), daemon=True).start()
        threading.Thread(target=self._load_analyzer, args=(anal_candidates,), daemon=True).start()

    def _load_openings(self, candidates):
        for path in candidates:
            if os.path.isfile(path):
                book = OpeningBook(path)
                if book.loaded:
                    self._opening_book = book
                    self._opening_path = path
                    n = len(book._entries)
                    self.root.after(0, lambda n=n, p=path: (
                        self._open_bar.stop(),
                        self._open_lbl.config(text=f"✓ {n} openings", fg="#1BECA0"),
                        self._status_var.set(f"Openings: {os.path.basename(p)}")
                    ))
                    self._openings_done = True
                    self.root.after(0, self._check_done)
                    return
        self.root.after(0, lambda: (
            self._open_bar.stop(),
            self._open_lbl.config(text="⚠ Not found", fg="#FF8800"),
        ))
        self._openings_done = True
        self.root.after(0, self._check_done)

    def _load_analyzer(self, candidates):
        found_path = None
        for p in candidates:
            if os.path.isfile(p):
                found_path = p
                break

        if not found_path:
            self.root.after(0, lambda: (
                self._anal_bar.stop(),
                self._anal_lbl.config(text="⚠ Not found", fg="#FF8800"),
            ))
            self._analyzer_done = True
            self.root.after(0, self._check_done)
            return

        self._analyzer_path = found_path
        try:
            eng = AnalyzerEngine(found_path, "Analyzer")
            eng.start()
            self._analyzer_eng = eng
            name = os.path.basename(found_path)
            self.root.after(0, lambda name=name: (
                self._anal_bar.stop(),
                self._anal_lbl.config(text=f"✓ {name}", fg="#1BECA0"),
            ))
        except Exception as e:
            print(f"[LoadingScreen] Analyzer error: {e}")
            self._analyzer_eng = None
            self.root.after(0, lambda: (
                self._anal_bar.stop(),
                self._anal_lbl.config(text="⚠ Failed", fg="#FF4444"),
            ))

        self._analyzer_done = True
        self.root.after(0, self._check_done)

    def _check_done(self):
        if not (self._openings_done and self._analyzer_done):
            return
        self._status_var.set("✓  Everything loaded — launching…")
        self.root.after(700, self._launch_main)

    def _launch_main(self):
        for w in self.root.winfo_children():
            w.destroy()

        self.root.resizable(True, True)
        self.root.minsize(1120, 860)
        self.root.geometry("")

        ChessGUI(self.root,
                 preloaded_book=self._opening_book,
                 preloaded_book_path=self._opening_path,
                 preloaded_analyzer=self._analyzer_eng,
                 preloaded_analyzer_path=self._analyzer_path)


# ═══════════════════════════════════════════════════════════
#  GUI
# ═══════════════════════════════════════════════════════════

class ChessGUI:
    def __init__(self, root,
                 preloaded_book=None,
                 preloaded_book_path=None,
                 preloaded_analyzer=None,
                 preloaded_analyzer_path=None):
        self.root=root
        self.root.title("♟  Chess Engine Arena — Enhanced")
        self.root.configure(bg=BG)
        self.root.resizable(True,True)
        self.root.minsize(1120,860)
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

        self.board=Board()
        self.engine1=None; self.engine2=None

        self._analyzer_lock = threading.Lock()
        self._last_eval_cp  = None
        self._last_quality  = None
        self._move_qualities = []

        if preloaded_book and preloaded_book.loaded:
            self.opening_book      = preloaded_book
            self._opening_csv_path = preloaded_book_path
        else:
            self.opening_book      = OpeningBook()
            self._opening_csv_path = None

        self._analyzer_path = preloaded_analyzer_path
        if preloaded_analyzer and preloaded_analyzer.alive:
            self.analyzer = preloaded_analyzer
        else:
            self.analyzer = None

        self.e1_path=tk.StringVar(); self.e2_path=tk.StringVar()
        self.e1_name=tk.StringVar(value="Engine 1 (Black)")
        self.e2_name=tk.StringVar(value="Engine 2 (White)")
        self.movetime=tk.IntVar(value=1000)
        self.delay   =tk.DoubleVar(value=0.5)

        self.play_mode = tk.StringVar(value="engine_vs_engine")
        self.player_name = tk.StringVar(value="Player")
        self.player_color = tk.StringVar(value="white")

        self.game_running=False; self.game_paused=False
        self.game_thread=None; self.last_move=None
        self.game_result=''; self.game_date=''
        self.sq_size=74
        self.flipped=False
        self._pending_b=None
        self.board_lock = threading.Lock()
        self._engine_thinking = False

        self.e1_eval =tk.StringVar(value='—')
        self.e2_eval =tk.StringVar(value='—')
        self.e1_depth=tk.StringVar(value='—')
        self.e2_depth=tk.StringVar(value='—')

        self._eval_bar_cp = 0

        self.opening_var = tk.StringVar(value="")
        self.current_opening_name = None

        self.db_path = get_db_path()
        self._init_database()

        self._build_ui()
        self._draw_board()
        self._reset_opening()

        self._update_book_lbl()
        self._update_analyzer_lbl()
        if self.opening_book and self.opening_book.loaded:
            short = os.path.basename(self._opening_csv_path or "")
            self.root.title(
                f"♟  Chess Engine Arena — {len(self.opening_book._entries)} openings ({short})")
        book_status = (f"📖 {len(self.opening_book._entries)} openings loaded"
                       if self.opening_book.loaded else "⚠ No openings CSV")
        self._status(
            f"DB: {self.db_path} | {book_status} | Ready — load engines and press ▶ Start")

        self.root.after(100, self._draw_eval_bar, 0)
        self.root.after(300, self._refresh_banners)

    def _on_closing(self):
        self.game_running = False
        self.game_paused  = False
        self._engine_thinking = False
        def _shutdown():
            try: self._kill_engines()
            except: pass
            if self.analyzer:
                try: self.analyzer.stop()
                except: pass
        threading.Thread(target=_shutdown, daemon=True).start()
        self.root.after(300, self.root.destroy)

    # ─── Eval bar drawing ─────────────────────────────────────────────────────

    def _draw_eval_bar(self, cp=None):
        if cp is not None:
            self._eval_bar_cp = cp
        self.eval_canvas.delete('all')

        bar_h = self.eval_canvas.winfo_height() or 592
        bar_w = self.eval_canvas.winfo_width() or 20

        cp_val = max(-1000, min(1000, self._eval_bar_cp))
        import math
        ratio = 0.5 + 0.5 * math.tanh(cp_val / 400.0)
        white_h = int(bar_h * ratio)
        black_h = bar_h - white_h

        self.eval_canvas.create_rectangle(0, 0, bar_w, black_h, fill="#1A1A1A", outline='')
        self.eval_canvas.create_rectangle(0, black_h, bar_w, bar_h, fill="#F0F0F0", outline='')
        self.eval_canvas.create_line(0, bar_h//2, bar_w, bar_h//2, fill="#444", width=1)
        if abs(cp_val) >= 29000:
            txt = "M" if cp_val > 0 else "-M"
        else:
            txt = f"{cp_val/100:+.1f}"
        if cp_val >= 0:
            ty = max(black_h - 10, 8)
            fg = "#EEE"
        else:
            ty = min(black_h + 10, bar_h - 8)
            fg = "#222"
        self.eval_canvas.create_text(bar_w//2, ty, text=txt, font=('Consolas', 7, 'bold'),
                                      fill=fg, anchor='center')
        self.eval_canvas.create_rectangle(0, 0, bar_w-1, bar_h-1, outline="#555", width=1)

    def _update_eval_from_engine(self, engine, side):
        if not engine: return
        info = engine.last_info
        sc = info.get('score')
        st = info.get('score_type', 'cp')
        if sc is None: return

        if st == 'mate':
            cp = 30000 if sc > 0 else -30000
        else:
            cp = sc
        if side == 'b':
            cp = -cp

        self._eval_bar_cp = cp
        self.root.after(0, self._draw_eval_bar, cp)

    # ─── Move quality analysis ────────────────────────────────────────────────

    def _analyze_move_quality(self, uci_before, uci_after, was_white_moving, san):
        if not self.analyzer or not self.analyzer.alive:
            return

        with self._analyzer_lock:
            cp_before, _ = self.analyzer.eval_position(uci_before, movetime_ms=200)
            cp_after,  _ = self.analyzer.eval_position(uci_after,  movetime_ms=200)

        if cp_before is None or cp_after is None:
            return

        quality = classify_move_quality(cp_before, cp_after, was_white_moving)

        ply = len(self.board.move_history)
        self._last_quality = quality
        self._last_eval_cp = cp_after
        self._move_qualities.append((ply, san, quality))

        self.root.after(0, lambda: self._on_quality_result(quality, cp_after, san))

    def _on_quality_result(self, quality, cp_after, san):
        self._draw_eval_bar(cp_after)
        self._update_quality_display(quality, san)

    def _update_quality_display(self, quality, san):
        if quality is None:
            self.quality_lbl.config(text="", bg=BG)
            return
        color = QUALITY_COLORS.get(quality, TEXT)
        self.quality_lbl.config(text=quality, fg=color, bg=BG)

    def _annotate_last_move(self, quality):
        pass

    def _trigger_quality_analysis(self, moves_before, moves_after, was_white, san):
        if not self.analyzer or not self.analyzer.alive:
            return
        t = threading.Thread(
            target=self._analyze_move_quality,
            args=(moves_before, moves_after, was_white, san),
            daemon=True)
        t.start()

    # ─── Opening helpers ──────────────────────────────────────────────────────

    def _refresh_opening(self):
        if not self.opening_book or not self.opening_book.loaded:
            return
        moves = self.board.uci_moves_list()
        eco, name = self.opening_book.lookup(moves)
        if name:
            self.current_opening_name = name
            display = f"📖  {eco}  ·  {name}" if eco else f"📖  {name}"
            self.opening_var.set(display)
        elif self.current_opening_name:
            self.opening_var.set(f"📖  {self.current_opening_name}")

    def _reset_opening(self):
        self.current_opening_name = None
        if self.opening_book and self.opening_book.loaded:
            self.opening_var.set(f"📖  {len(self.opening_book._entries)} openings ready")
        else:
            self.opening_var.set("⚠  No openings CSV — use 📂 Load Openings CSV button")

    def _update_book_lbl(self):
        if not hasattr(self, 'book_lbl'): return
        if self.opening_book and self.opening_book.loaded:
            name = os.path.basename(self._opening_csv_path) if self._opening_csv_path else "loaded"
            self.book_lbl.config(
                text=f"✓ {len(self.opening_book._entries)} openings  ({name})",
                fg="#00BFFF")
        else:
            self.book_lbl.config(text="⚠ No CSV loaded", fg="#FF8800")

    def _browse_csv(self):
        path = filedialog.askopenfilename(
            title="Select Openings CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path: return
        try:
            book = OpeningBook(path)
            if not book.loaded:
                messagebox.showerror("Error", f"No valid openings found in:\n{path}")
                return
            self.opening_book = book
            self._opening_csv_path = path
            self._update_book_lbl()
            self._reset_opening()
            messagebox.showinfo("Loaded",
                f"✓ {len(book._entries)} openings loaded from:\n{os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load CSV:\n{e}")

    def _browse_analyzer(self):
        path = filedialog.askopenfilename(
            title="Select Stockfish / Analyzer Engine",
            filetypes=[("Executables", "*.exe *.bin *"), ("All", "*.*")])
        if not path: return
        if self.analyzer:
            try: self.analyzer.stop()
            except: pass
            self.analyzer = None
        self._analyzer_path = path
        self._start_analyzer()
        if self.analyzer and self.analyzer.alive:
            self._update_analyzer_lbl()
            messagebox.showinfo("Analyzer", f"✓ Analyzer loaded:\n{os.path.basename(path)}")
        else:
            messagebox.showerror("Error", f"Could not start analyzer:\n{path}")

    def _start_analyzer(self):
        if not self._analyzer_path:
            return
        try:
            eng = AnalyzerEngine(self._analyzer_path, "Analyzer")
            eng.start()
            self.analyzer = eng
            print("[Analyzer] Started successfully")
            self._update_analyzer_lbl()
        except Exception as e:
            print(f"[Analyzer] Failed to start: {e}")
            self.analyzer = None
            self._update_analyzer_lbl()

    def _update_analyzer_lbl(self):
        if not hasattr(self, 'analyzer_lbl'): return
        if self.analyzer and self.analyzer.alive:
            name = os.path.basename(self._analyzer_path) if self._analyzer_path else "?"
            self.analyzer_lbl.config(text=f"🔍 {name}", fg="#1BECA0")
        else:
            self.analyzer_lbl.config(text="⚠ No analyzer", fg="#FF8800")

    # ─── Database methods ─────────────────────────────────────────────────────

    def _init_database(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                white_engine TEXT NOT NULL,
                black_engine TEXT NOT NULL,
                result TEXT NOT NULL,
                reason TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                pgn TEXT NOT NULL,
                move_count INTEGER,
                duration_seconds INTEGER
            )
        ''')
        conn.commit()
        conn.close()

    def _save_game_to_db(self, white_name, black_name, result, reason, pgn, duration_sec):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()
            date_str = datetime.now().strftime("%Y.%m.%d")
            time_str = datetime.now().strftime("%H:%M:%S")
            move_count = len(self.board.move_history)
            norm_white = normalize_engine_name(white_name)
            norm_black = normalize_engine_name(black_name)
            cursor.execute('''
                INSERT INTO games (white_engine, black_engine, result, reason, date, time, pgn, move_count, duration_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (norm_white, norm_black, result, reason, date_str, time_str, pgn, move_count, duration_sec))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"Database error: {e}")

    def _get_engine_stats(self, search_query=''):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT DISTINCT white_engine FROM games')
            whites = {normalize_engine_name(r[0]) for r in cursor.fetchall()}
            cursor.execute('SELECT DISTINCT black_engine FROM games')
            blacks = {normalize_engine_name(r[0]) for r in cursor.fetchall()}
            engines = sorted(whites | blacks)
            if search_query:
                q = search_query.lower()
                engines = [e for e in engines if q in e.lower()]
            stats = []
            for engine in engines:
                cursor.execute('SELECT COUNT(*) FROM games WHERE white_engine = ? OR black_engine = ?', (engine, engine))
                matches = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM games WHERE white_engine = ? AND result = '1-0'", (engine,))
                wins_white = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM games WHERE black_engine = ? AND result = '0-1'", (engine,))
                wins_black = cursor.fetchone()[0]
                wins = wins_white + wins_black
                cursor.execute("SELECT COUNT(*) FROM games WHERE (white_engine = ? OR black_engine = ?) AND result = '1/2-1/2'", (engine, engine))
                draws = cursor.fetchone()[0]
                loses = matches - wins - draws
                win_rate = (wins / matches * 100) if matches > 0 else 0
                stats.append({'engine': engine, 'matches': matches, 'wins': wins,
                              'draws': draws, 'loses': loses, 'win_rate': win_rate})
            conn.close()
            return stats
        except Exception as e:
            print(f"Database error: {e}")
            return []

    def _get_all_games_for_elo(self):
        """Get all games ordered oldest-first for Elo computation."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT white_engine, black_engine, result FROM games ORDER BY id ASC")
            rows = cursor.fetchall()
            conn.close()
            return rows
        except Exception as e:
            print(f"Database error (elo): {e}")
            return []

    def _get_all_games(self, filter_engine=None, search_query=''):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            if filter_engine:
                norm = normalize_engine_name(filter_engine)
                cursor.execute('''SELECT id, white_engine, black_engine, result, reason, date, time, move_count, duration_seconds
                    FROM games WHERE white_engine = ? OR black_engine = ? ORDER BY id DESC''', (norm, norm))
            else:
                cursor.execute('''SELECT id, white_engine, black_engine, result, reason, date, time, move_count, duration_seconds
                    FROM games ORDER BY id DESC''')
            games = cursor.fetchall()
            conn.close()
            if search_query:
                q = search_query.lower()
                filtered = []
                for g in games:
                    haystack = ' '.join(str(v) for v in g).lower()
                    if q in haystack:
                        filtered.append(g)
                return filtered
            return games
        except Exception as e:
            print(f"Database error: {e}")
            return []

    def _get_game_pgn(self, game_id):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT pgn FROM games WHERE id = ?', (game_id,))
            result = cursor.fetchone()
            conn.close()
            return result[0] if result else None
        except Exception as e:
            print(f"Database error: {e}")
            return None

    # ═══════════════════════════════════════════════════════════
    #  RANKINGS WINDOW  ← NEW
    # ═══════════════════════════════════════════════════════════

    def _show_rankings(self):
        """Show the Engine Rankings leaderboard with Elo ratings."""
        win = tk.Toplevel(self.root)
        win.title("🏆 Engine Rankings")
        win.configure(bg=BG)
        win.geometry("860x680")
        win.resizable(True, True)

        # ── Header ────────────────────────────────────────────
        hdr_frame = tk.Frame(win, bg=BG)
        hdr_frame.pack(fill='x', padx=20, pady=(14, 0))

        tk.Label(hdr_frame, text="🏆", bg=BG, fg=ACCENT,
                 font=('Segoe UI', 28)).pack(side='left', padx=(0, 10))
        title_f = tk.Frame(hdr_frame, bg=BG)
        title_f.pack(side='left')
        tk.Label(title_f, text="ENGINE RANKINGS", bg=BG, fg=ACCENT,
                 font=('Segoe UI', 18, 'bold')).pack(anchor='w')
        tk.Label(title_f, text="Elo ratings calculated from all recorded games",
                 bg=BG, fg="#666", font=('Segoe UI', 9)).pack(anchor='w')

        tk.Frame(win, bg=ACCENT, height=2).pack(fill='x', padx=20, pady=(10, 8))

        # ── Tier legend ───────────────────────────────────────
        legend_frame = tk.Frame(win, bg=PANEL_BG)
        legend_frame.pack(fill='x', padx=20, pady=(0, 8))
        tk.Label(legend_frame, text="  Tiers: ", bg=PANEL_BG, fg="#AAA",
                 font=('Segoe UI', 8)).pack(side='left')
        for threshold, label, color in RANK_TIERS:
            tk.Label(legend_frame, text=f"  {label} ≥{threshold}" if threshold > 0 else f"  {label}",
                     bg=PANEL_BG, fg=color, font=('Segoe UI', 8)).pack(side='left')

        # ── Search bar ────────────────────────────────────────
        sb_container = tk.Frame(win, bg=BG)
        sb_container.pack(fill='x', padx=20, pady=(0, 6))

        all_data_ref = [None]
        tree_ref     = [None]
        count_lbl    = [None]

        def refresh(query=''):
            games_raw = self._get_all_games_for_elo()
            elo_ratings = compute_elo_ratings(games_raw)
            stats_list  = self._get_engine_stats()
            stats_map   = {s['engine']: s for s in stats_list}

            rows = []
            for engine, elo in elo_ratings.items():
                s = stats_map.get(engine, {})
                matches  = s.get('matches', 0)
                wins     = s.get('wins', 0)
                draws    = s.get('draws', 0)
                loses    = s.get('loses', 0)
                win_rate = s.get('win_rate', 0.0)
                tier_lbl, tier_col = get_tier(elo)
                rows.append({
                    'engine':   engine,
                    'elo':      elo,
                    'tier':     tier_lbl,
                    'tier_col': tier_col,
                    'matches':  matches,
                    'wins':     wins,
                    'draws':    draws,
                    'loses':    loses,
                    'win_rate': win_rate,
                })

            rows.sort(key=lambda x: x['elo'], reverse=True)

            if query:
                q = query.lower()
                rows = [r for r in rows if q in r['engine'].lower() or q in r['tier'].lower()]

            all_data_ref[0] = rows
            _render(rows)

        def _render(rows):
            tree = tree_ref[0]
            if not tree: return
            for item in tree.get_children():
                tree.delete(item)

            for rank, row in enumerate(rows, 1):
                medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")
                tree.insert('', 'end',
                    values=(
                        medal,
                        row['engine'],
                        row['elo'],
                        row['tier'],
                        row['matches'],
                        row['wins'],
                        row['draws'],
                        row['loses'],
                        f"{row['win_rate']:.1f}%",
                    ),
                    tags=(row['tier_col'],)
                )

            if count_lbl[0]:
                count_lbl[0].config(text=f"{len(rows)} engine(s) ranked")

        sb_frame, _ = make_search_bar(sb_container, refresh, placeholder="🔍 Filter engines or tiers…")
        sb_frame.pack(fill='x')

        # ── Treeview ──────────────────────────────────────────
        tree_frame = tk.Frame(win, bg=BG)
        tree_frame.pack(fill='both', expand=True, padx=20, pady=(0, 4))

        scrollbar = tk.Scrollbar(tree_frame)
        scrollbar.pack(side='right', fill='y')

        columns = ('Rank', 'Engine', 'Elo', 'Tier', 'Games', 'W', 'D', 'L', 'WR%')
        tree = ttk.Treeview(tree_frame, columns=columns, show='headings',
                            yscrollcommand=scrollbar.set)
        scrollbar.config(command=tree.yview)
        tree_ref[0] = tree

        col_cfg = [
            ('Rank',   55,  'center'),
            ('Engine', 230, 'w'),
            ('Elo',    70,  'center'),
            ('Tier',   140, 'w'),
            ('Games',  55,  'center'),
            ('W',      45,  'center'),
            ('D',      45,  'center'),
            ('L',      45,  'center'),
            ('WR%',    65,  'center'),
        ]
        for col, w, anch in col_cfg:
            tree.column(col, width=w, anchor=anch)
            tree.heading(col, text=col)

        # Color rows by tier
        for _, label, color in RANK_TIERS:
            tree.tag_configure(color, foreground=color)

        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Treeview', background=LOG_BG, foreground=TEXT,
                        fieldbackground=LOG_BG, borderwidth=0, rowheight=28)
        style.configure('Treeview.Heading', background=BTN_BG, foreground=TEXT,
                        borderwidth=1, font=('Segoe UI', 9, 'bold'))
        style.map('Treeview', background=[('selected', ACCENT)])
        style.map('Treeview.Heading', background=[('active', ACCENT)])
        tree.pack(fill='both', expand=True)

        count_lbl[0] = tk.Label(win, text="", bg=BG, fg="#555", font=('Segoe UI', 9))
        count_lbl[0].pack(pady=(2, 0))

        tk.Label(win,
                 text="💡 Double-click a row to see Elo history  ·  Elo starts at 1500, K=32",
                 bg=BG, fg="#444", font=('Segoe UI', 8)).pack(pady=(0, 4))

        def on_double_click(event):
            sel = tree.selection()
            if not sel: return
            item = tree.item(sel[0])
            vals = item['values']
            engine_name = vals[1]
            self._show_elo_history(engine_name)

        tree.bind('<Double-1>', on_double_click)

        # ── Footer buttons ────────────────────────────────────
        btn_frame = tk.Frame(win, bg=BG)
        btn_frame.pack(fill='x', padx=20, pady=(0, 14))

        tk.Button(btn_frame, text="🔄 Refresh", command=lambda: refresh(''),
                  bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
                  padx=15, pady=8, cursor='hand2', relief='flat').pack(side='left', padx=5)
        tk.Button(btn_frame, text="📊 Statistics",
                  command=self._show_statistics,
                  bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
                  padx=15, pady=8, cursor='hand2', relief='flat').pack(side='left', padx=5)
        tk.Button(btn_frame, text="✕ Close", command=win.destroy,
                  bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
                  padx=15, pady=8, cursor='hand2', relief='flat').pack(side='right', padx=5)

        refresh('')

    # ─── Elo history chart ────────────────────────────────────────────────────

    def _show_elo_history(self, engine_name):
        """Draw a simple Elo rating history for one engine."""
        games_raw = self._get_all_games_for_elo()
        history = compute_elo_history(games_raw, engine_name)

        if not history:
            messagebox.showinfo("No Data", f"No games found for:\n{engine_name}")
            return

        win = tk.Toplevel(self.root)
        win.title(f"📈 Elo History — {engine_name}")
        win.configure(bg=BG)
        win.geometry("700x500")
        win.resizable(True, True)

        tk.Label(win, text=f"📈 Elo History: {engine_name}",
                 bg=BG, fg=ACCENT, font=('Segoe UI', 14, 'bold')).pack(pady=(14, 4))

        final_elo = history[-1][1]
        tier_lbl, tier_col = get_tier(final_elo)
        tk.Label(win, text=f"Current Rating: {final_elo}  ·  {tier_lbl}",
                 bg=BG, fg=tier_col, font=('Segoe UI', 11, 'bold')).pack(pady=(0, 8))

        tk.Frame(win, bg=ACCENT, height=2).pack(fill='x', padx=20)

        # ── Canvas chart ──────────────────────────────────────
        chart_frame = tk.Frame(win, bg=BG)
        chart_frame.pack(fill='both', expand=True, padx=20, pady=12)

        canvas = tk.Canvas(chart_frame, bg=LOG_BG, highlightthickness=1,
                           highlightbackground='#333')
        canvas.pack(fill='both', expand=True)

        def draw_chart(event=None):
            canvas.delete('all')
            cw = canvas.winfo_width()  or 660
            ch = canvas.winfo_height() or 360

            pad_l, pad_r, pad_t, pad_b = 60, 20, 20, 40
            plot_w = cw - pad_l - pad_r
            plot_h = ch - pad_t - pad_b

            elos = [h[1] for h in history]
            min_elo = max(0, min(elos) - 50)
            max_elo = max(elos) + 50
            elo_range = max_elo - min_elo or 1
            n = len(history)

            # Background grid
            for i in range(5):
                gy = pad_t + int(plot_h * i / 4)
                canvas.create_line(pad_l, gy, pad_l + plot_w, gy,
                                   fill="#222", dash=(4, 4))
                ev = max_elo - int(elo_range * i / 4)
                canvas.create_text(pad_l - 6, gy, text=str(ev),
                                   fill="#666", font=('Consolas', 8), anchor='e')

            # Y-axis label
            canvas.create_text(12, ch // 2, text="Elo", fill="#666",
                               font=('Consolas', 8), angle=90)

            # Plot Elo line with tier-colored segments
            def elo_y(e):
                return pad_t + int(plot_h * (1 - (e - min_elo) / elo_range))

            def game_x(i):
                if n == 1:
                    return pad_l + plot_w // 2
                return pad_l + int(plot_w * i / (n - 1))

            # Draw tier zone backgrounds
            for k, (threshold, _, color) in enumerate(RANK_TIERS):
                next_thresh = RANK_TIERS[k - 1][0] if k > 0 else 9999
                y1 = pad_t
                y2 = pad_t + plot_h
                if next_thresh > max_elo:
                    y1_clipped = pad_t
                else:
                    y1_clipped = elo_y(min(next_thresh, max_elo))
                if threshold < min_elo:
                    y2_clipped = pad_t + plot_h
                else:
                    y2_clipped = elo_y(max(threshold, min_elo))
                if y1_clipped < y2_clipped:
                    canvas.create_rectangle(pad_l, y1_clipped, pad_l + plot_w, y2_clipped,
                                           fill=color, stipple='gray12', outline='')

            # Draw the line
            points = [(game_x(i), elo_y(e)) for i, (_, e) in enumerate(history)]
            if len(points) > 1:
                for i in range(len(points) - 1):
                    e1 = history[i][1]
                    e2 = history[i + 1][1]
                    mid_e = (e1 + e2) / 2
                    _, seg_col = get_tier(int(mid_e))
                    canvas.create_line(points[i][0], points[i][1],
                                      points[i+1][0], points[i+1][1],
                                      fill=seg_col, width=2, smooth=True)

            # Draw data points
            for i, (gn, e) in enumerate(history):
                x, y = game_x(i), elo_y(e)
                _, pt_col = get_tier(e)
                canvas.create_oval(x - 4, y - 4, x + 4, y + 4,
                                  fill=pt_col, outline='white', width=1)

            # X-axis labels
            step = max(1, n // 8)
            for i in range(0, n, step):
                x = game_x(i)
                canvas.create_text(x, ch - pad_b + 12, text=str(history[i][0]),
                                  fill="#555", font=('Consolas', 8))
            canvas.create_text(pad_l + plot_w // 2, ch - 8,
                               text="Game #", fill="#555", font=('Consolas', 8))

            # Starting / ending rating annotation
            if history:
                canvas.create_text(game_x(0), elo_y(history[0][1]) - 12,
                                  text=str(history[0][1]), fill="#AAA",
                                  font=('Consolas', 8))
                canvas.create_text(game_x(n - 1), elo_y(history[-1][1]) - 12,
                                  text=str(history[-1][1]), fill=tier_col,
                                  font=('Consolas', 9, 'bold'))

        canvas.bind('<Configure>', draw_chart)
        win.after(100, draw_chart)

        # Stats summary row
        if len(elos) > 1:
            peak = max(elos)
            lowest = min(elos)
            change = elos[-1] - elos[0]
            chg_str = f"+{change}" if change >= 0 else str(change)
            chg_col = "#00FF80" if change >= 0 else "#FF4444"
            summary_f = tk.Frame(win, bg=PANEL_BG)
            summary_f.pack(fill='x', padx=20, pady=(0, 4))
            for label, val, col in [
                ("Peak", str(peak), "#FFD700"),
                ("Lowest", str(lowest), "#FF6B6B"),
                ("Change", chg_str, chg_col),
                ("Games", str(n), TEXT),
            ]:
                sf = tk.Frame(summary_f, bg=PANEL_BG)
                sf.pack(side='left', expand=True)
                tk.Label(sf, text=label, bg=PANEL_BG, fg="#666",
                         font=('Segoe UI', 8)).pack()
                tk.Label(sf, text=val, bg=PANEL_BG, fg=col,
                         font=('Segoe UI', 12, 'bold')).pack()

        tk.Button(win, text="✕ Close", command=win.destroy,
                  bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
                  padx=20, pady=8, cursor='hand2', relief='flat').pack(pady=(0, 12))

    # ─── Statistics window ────────────────────────────────────────────────────

    def _show_statistics(self):
        stats_window = tk.Toplevel(self.root)
        stats_window.title("Engine Statistics")
        stats_window.configure(bg=BG)
        stats_window.geometry("720x580")

        tk.Label(stats_window, text="📊 ENGINE STATISTICS", bg=BG, fg=ACCENT,
                 font=('Segoe UI', 16, 'bold')).pack(pady=(12, 2))
        tk.Label(stats_window, text=f"📁 {self.db_path}", bg=BG, fg="#555",
                 font=('Consolas', 8), wraplength=700).pack(pady=(0, 6))

        search_frame = tk.Frame(stats_window, bg=BG)
        search_frame.pack(fill='x', padx=20, pady=(0, 6))

        all_stats = [None]
        tree_ref  = [None]
        sort_state = {'col': None, 'reverse': False}

        COL_META = {
            'Engine':   ('engine',   str),
            'Matches':  ('matches',  int),
            'Win':      ('wins',     int),
            'Draw':     ('draws',    int),
            'Lose':     ('loses',    int),
            'WinRate%': ('win_rate', float),
        }
        BASE_LABELS = {c: c for c in COL_META}

        def _render_rows(stats):
            tree = tree_ref[0]
            if tree is None:
                return
            for row in tree.get_children():
                tree.delete(row)
            for stat in stats:
                tree.insert('', 'end', values=(
                    stat['engine'], stat['matches'], stat['wins'],
                    stat['draws'], stat['loses'], f"{stat['win_rate']:.1f}%"))

        def _update_headings():
            tree = tree_ref[0]
            if tree is None:
                return
            columns = ('Engine', 'Matches', 'Win', 'Draw', 'Lose', 'WinRate%')
            for col in columns:
                label = BASE_LABELS[col]
                if col == sort_state['col']:
                    label += ' \u25bc' if sort_state['reverse'] else ' \u25b2'
                tree.heading(col, text=label, command=lambda c=col: sort_by_column(c))

        def sort_by_column(col):
            stats = all_stats[0]
            if not stats:
                return
            if sort_state['col'] == col:
                sort_state['reverse'] = not sort_state['reverse']
            else:
                sort_state['col'] = col
                sort_state['reverse'] = False

            key_name, key_type = COL_META[col]
            sorted_stats = sorted(
                stats,
                key=lambda x: x[key_name],
                reverse=sort_state['reverse']
            )
            all_stats[0] = sorted_stats
            _render_rows(sorted_stats)
            _update_headings()
            count_lbl.config(text=f"{len(sorted_stats)} engine(s) shown")

        def refresh_stats(query=''):
            stats = self._get_engine_stats(search_query=query)
            all_stats[0] = stats
            if sort_state['col']:
                key_name, _ = COL_META[sort_state['col']]
                stats = sorted(stats, key=lambda x: x[key_name],
                               reverse=sort_state['reverse'])
                all_stats[0] = stats
            _render_rows(stats)
            _update_headings()
            count_lbl.config(text=f"{len(stats)} engine(s) shown")

        sb_frame, _ = make_search_bar(search_frame, refresh_stats, placeholder="🔍 Filter engines…")
        sb_frame.pack(fill='x')

        tree_frame = tk.Frame(stats_window, bg=BG)
        tree_frame.pack(fill='both', expand=True, padx=20, pady=(0, 4))
        scrollbar = tk.Scrollbar(tree_frame)
        scrollbar.pack(side='right', fill='y')

        columns = ('Engine', 'Matches', 'Win', 'Draw', 'Lose', 'WinRate%')
        tree = ttk.Treeview(tree_frame, columns=columns, show='headings',
                            yscrollcommand=scrollbar.set)
        scrollbar.config(command=tree.yview)
        tree_ref[0] = tree

        tree.column('Engine',   width=260)
        tree.column('Matches',  width=75,  anchor='center')
        tree.column('Win',      width=55,  anchor='center')
        tree.column('Draw',     width=55,  anchor='center')
        tree.column('Lose',     width=55,  anchor='center')
        tree.column('WinRate%', width=90,  anchor='center')

        for col in columns:
            tree.heading(col, text=col, command=lambda c=col: sort_by_column(c))

        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Treeview', background=LOG_BG, foreground=TEXT,
                        fieldbackground=LOG_BG, borderwidth=0)
        style.configure('Treeview.Heading', background=BTN_BG, foreground=TEXT,
                        borderwidth=1, font=('Segoe UI', 9, 'bold'))
        style.map('Treeview', background=[('selected', ACCENT)])
        style.map('Treeview.Heading', background=[('active', ACCENT)])
        tree.pack(fill='both', expand=True)

        count_lbl = tk.Label(stats_window, text="", bg=BG, fg="#555",
                             font=('Segoe UI', 9))
        count_lbl.pack(pady=(0, 2))

        tip = tk.Label(
            stats_window,
            text="💡 Click a column header to sort  ·  Double-click a row to view game history",
            bg=BG, fg="#555", font=('Segoe UI', 9))
        tip.pack(pady=(0, 4))

        def on_engine_double_click(event):
            selected = tree.selection()
            if not selected: return
            item = tree.item(selected[0])
            engine_name = item['values'][0]
            self._show_game_history(filter_engine=engine_name)

        tree.bind('<Double-1>', on_engine_double_click)

        btn_frame = tk.Frame(stats_window, bg=BG)
        btn_frame.pack(fill='x', padx=20, pady=(0, 12))

        shortcuts = tk.Frame(btn_frame, bg=BG)
        shortcuts.pack(side='left')
        tk.Label(shortcuts, text="Sort by:", bg=BG, fg="#888",
                 font=('Segoe UI', 8)).pack(side='left', padx=(0, 4))
        for label, col in [("Matches", "Matches"), ("Wins", "Win"), ("Win%", "WinRate%")]:
            tk.Button(shortcuts, text=label,
                      command=lambda c=col: sort_by_column(c),
                      bg=BTN_BG, fg=TEXT, font=('Segoe UI', 8),
                      padx=8, pady=4, cursor='hand2', relief='flat').pack(side='left', padx=2)

        tk.Button(btn_frame, text="🏆 Rankings",
                  command=self._show_rankings,
                  bg=ACCENT, fg=TEXT, font=('Segoe UI', 10, 'bold'),
                  padx=15, pady=8, cursor='hand2', relief='flat').pack(side='left', padx=(10, 5))
        tk.Button(btn_frame, text="View All Game History",
                  command=lambda: self._show_game_history(),
                  bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
                  padx=15, pady=8, cursor='hand2').pack(side='left', padx=5)
        tk.Button(btn_frame, text="Refresh",
                  command=lambda: refresh_stats(''),
                  bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
                  padx=15, pady=8, cursor='hand2').pack(side='left', padx=5)
        tk.Button(btn_frame, text="Close",
                  command=stats_window.destroy,
                  bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
                  padx=15, pady=8, cursor='hand2').pack(side='right', padx=5)

        refresh_stats('')

    # ─── Game history window ──────────────────────────────────────────────────

    def _show_game_history(self, filter_engine=None):
        history_window = tk.Toplevel(self.root)
        norm_filter = normalize_engine_name(filter_engine) if filter_engine else None
        history_window.title(f"Game History{' — ' + norm_filter if norm_filter else ''}")
        history_window.configure(bg=BG)
        history_window.geometry("960x640")

        header_frame = tk.Frame(history_window, bg=BG)
        header_frame.pack(fill='x', padx=20, pady=(12, 0))
        tk.Label(header_frame, text="📜 GAME HISTORY", bg=BG, fg=ACCENT,
                 font=('Segoe UI', 16, 'bold')).pack(side='left')
        if norm_filter:
            tk.Label(header_frame, text=f"  ·  {norm_filter}", bg=BG, fg="#FFD700",
                     font=('Segoe UI', 11)).pack(side='left')
            tk.Button(header_frame, text="✕ Clear Filter",
                      command=lambda: [history_window.destroy(), self._show_game_history()],
                      bg=BTN_BG, fg=TEXT, font=('Segoe UI', 9), padx=10, pady=4,
                      cursor='hand2', relief='flat').pack(side='right')

        search_container = tk.Frame(history_window, bg=BG)
        search_container.pack(fill='x', padx=20, pady=(8, 4))

        all_games_cache = [None]
        tree_ref2       = [None]
        count_lbl2      = [None]

        def refresh_history(query=''):
            games = self._get_all_games(filter_engine=filter_engine, search_query=query)
            all_games_cache[0] = games
            tree = tree_ref2[0]
            if tree is None: return
            for row in tree.get_children(): tree.delete(row)
            for game in games:
                game_id, white, black, result, reason, date, time_str, moves, duration = game
                duration_str = f"{duration//60}m {duration%60}s" if duration else "N/A"
                tree.insert('', 'end', values=(game_id, date, time_str, white, black,
                                               result, reason, moves or 0, duration_str))
            if count_lbl2[0]:
                count_lbl2[0].config(text=f"{len(games)} game(s) shown")

        sb_frame2, _ = make_search_bar(search_container, refresh_history,
                                        placeholder="🔍 Search by engine, result, reason, date…")
        sb_frame2.pack(fill='x')

        tree_frame = tk.Frame(history_window, bg=BG)
        tree_frame.pack(fill='both', expand=True, padx=20, pady=(4, 0))
        scrollbar = tk.Scrollbar(tree_frame)
        scrollbar.pack(side='right', fill='y')

        columns = ('ID', 'Date', 'Time', 'White', 'Black', 'Result', 'Reason', 'Moves', 'Duration')
        tree = ttk.Treeview(tree_frame, columns=columns, show='headings', yscrollcommand=scrollbar.set)
        scrollbar.config(command=tree.yview)
        tree_ref2[0] = tree

        for col, w in [('ID',40),('Date',80),('Time',70),('White',150),('Black',150),
                       ('Result',60),('Reason',150),('Moves',50),('Duration',80)]:
            tree.heading(col, text=col)
            anchor = 'center' if col not in ('White','Black','Reason') else 'w'
            tree.column(col, width=w, anchor=anchor)
        tree.pack(fill='both', expand=True)

        count_lbl2[0] = tk.Label(history_window, text="", bg=BG, fg="#555", font=('Segoe UI', 9))
        count_lbl2[0].pack(pady=(2, 0))

        tk.Label(history_window,
                 text="💡 Double-click a row to view PGN   |   Click White/Black cell to filter by engine",
                 bg=BG, fg="#444", font=('Segoe UI', 8)).pack(pady=(0, 4))

        def _on_tree_click(event, double=False):
            region = tree.identify_region(event.x, event.y)
            if region != 'cell': return
            col_id  = tree.identify_column(event.x)
            row_id  = tree.identify_row(event.y)
            if not row_id: return
            col_index = int(col_id.replace('#', '')) - 1
            item = tree.item(row_id)
            values = item['values']
            if double:
                game_id = values[0]
                pgn = self._get_game_pgn(game_id)
                if pgn:
                    self._show_pgn_viewer(pgn, values, all_games_cache[0] or [], tree)
                else:
                    messagebox.showerror("Error", "Could not load PGN.")
            else:
                if col_index == 3:
                    history_window.destroy()
                    self._show_game_history(filter_engine=values[3])
                elif col_index == 4:
                    history_window.destroy()
                    self._show_game_history(filter_engine=values[4])

        tree.bind('<Button-1>',  lambda e: _on_tree_click(e, double=False))
        tree.bind('<Double-1>',  lambda e: _on_tree_click(e, double=True))

        btn_frame = tk.Frame(history_window, bg=BG)
        btn_frame.pack(fill='x', padx=20, pady=(4, 12))

        def view_pgn():
            selected = tree.selection()
            if not selected:
                messagebox.showinfo("No Selection", "Please select a game."); return
            item = tree.item(selected[0])
            game_id = item['values'][0]
            pgn = self._get_game_pgn(game_id)
            if pgn:
                self._show_pgn_viewer(pgn, item['values'], all_games_cache[0] or [], tree)
            else:
                messagebox.showerror("Error", "Could not load PGN.")

        tk.Button(btn_frame, text="View PGN", command=view_pgn, bg=ACCENT, fg=TEXT,
                  font=('Segoe UI', 10, 'bold'), padx=15, pady=8, cursor='hand2').pack(side='left', padx=5)
        if norm_filter:
            tk.Button(btn_frame, text="Show All Games",
                      command=lambda: [history_window.destroy(), self._show_game_history()],
                      bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10), padx=15, pady=8, cursor='hand2').pack(side='left', padx=5)
        tk.Button(btn_frame, text="Refresh", command=lambda: refresh_history(''),
                  bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10), padx=15, pady=8, cursor='hand2').pack(side='left', padx=5)
        tk.Button(btn_frame, text="Close", command=history_window.destroy,
                  bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10), padx=15, pady=8, cursor='hand2').pack(side='right', padx=5)

        refresh_history('')

    # ─── PGN viewer ───────────────────────────────────────────────────────────

    def _show_pgn_viewer(self, pgn, game_info, all_games, tree_ref=None):
        pgn_window = tk.Toplevel(self.root)
        pgn_window.title(f"PGN Viewer - Game #{game_info[0]}")
        pgn_window.configure(bg=BG)
        pgn_window.geometry("1000x700")
        current_game_id = game_info[0]
        current_index = None
        for idx, game in enumerate(all_games):
            if game[0] == current_game_id:
                current_index = idx
                break

        def load_game(direction):
            if current_index is None: return
            new_index = current_index + direction
            if 0 <= new_index < len(all_games):
                game = all_games[new_index]
                new_pgn = self._get_game_pgn(game[0])
                if new_pgn:
                    pgn_window.destroy()
                    game_id, white, black, result, reason, date, time_str, moves, duration = game
                    duration_str = f"{duration//60}m {duration%60}s" if duration else "N/A"
                    new_game_info = (game_id, date, time_str, white, black, result, reason, moves, duration_str)
                    self._show_pgn_viewer(new_pgn, new_game_info, all_games, tree_ref)

        top_nav = tk.Frame(pgn_window, bg=PANEL_BG)
        top_nav.pack(fill='x', padx=10, pady=(10, 5))
        tk.Button(top_nav, text="◀ Previous Game", command=lambda: load_game(-1),
                  bg=BTN_BG, fg=TEXT, font=('Segoe UI', 9, 'bold'), padx=10, pady=5,
                  cursor='hand2', relief='flat',
                  state='normal' if current_index and current_index > 0 else 'disabled').pack(side='left', padx=5)
        tk.Label(top_nav,
                 text=f"Game {current_index + 1 if current_index is not None else '?'} of {len(all_games)}",
                 bg=PANEL_BG, fg=ACCENT, font=('Segoe UI', 10, 'bold')).pack(side='left', expand=True)
        tk.Button(top_nav, text="Next Game ▶", command=lambda: load_game(1),
                  bg=BTN_BG, fg=TEXT, font=('Segoe UI', 9, 'bold'), padx=10, pady=5,
                  cursor='hand2', relief='flat',
                  state='normal' if current_index is not None and current_index < len(all_games) - 1 else 'disabled').pack(side='right', padx=5)

        main_container = tk.Frame(pgn_window, bg=BG)
        main_container.pack(fill='both', expand=True, padx=10, pady=5)

        left_frame = tk.Frame(main_container, bg=BG)
        left_frame.pack(side='left', fill='both', expand=True, padx=(0, 10))

        info_frame = tk.Frame(left_frame, bg=PANEL_BG)
        info_frame.pack(fill='x', pady=(0, 10))
        tk.Label(info_frame, text=f"Game #{game_info[0]} - {game_info[1]} {game_info[2]}",
                 bg=PANEL_BG, fg=ACCENT, font=('Segoe UI', 12, 'bold')).pack(pady=5)
        tk.Label(info_frame, text=f"White: {game_info[3]}", bg=PANEL_BG, fg="#FFD700",
                 font=('Segoe UI', 10)).pack(anchor='w', padx=10)
        tk.Label(info_frame, text=f"Black: {game_info[4]}", bg=PANEL_BG, fg="#C8C8C8",
                 font=('Segoe UI', 10)).pack(anchor='w', padx=10)
        tk.Label(info_frame, text=f"Result: {game_info[5]} - {game_info[6]}", bg=PANEL_BG, fg=TEXT,
                 font=('Segoe UI', 10)).pack(anchor='w', padx=10, pady=(0, 5))

        board_frame = tk.Frame(left_frame, bg=BG)
        board_frame.pack(pady=10)
        replay_board = Board()
        replay_size = 60
        replay_canvas = tk.Canvas(board_frame, width=replay_size*8, height=replay_size*8,
                                   bg=BG, bd=0, highlightthickness=2,
                                   highlightcolor=ACCENT, highlightbackground='#333')
        replay_canvas.pack()
        moves_list = self._parse_pgn_moves(pgn)
        current_move_index = [0]

        replay_opening_var = tk.StringVar(value="")
        tk.Label(left_frame, textvariable=replay_opening_var,
                 bg=BG, fg="#00BFFF", font=('Segoe UI', 9, 'italic'), anchor='center').pack(fill='x', padx=4)

        def _update_replay_opening():
            moves = replay_board.uci_moves_list()
            eco, name = self.opening_book.lookup(moves)
            if name:
                replay_opening_var.set(f"📖 {eco}  ·  {name}" if eco else f"📖 {name}")
            else:
                replay_opening_var.set("")

        def draw_replay_board(highlight_move=None):
            replay_canvas.delete('all')
            lm_from = lm_to = None
            if highlight_move and len(highlight_move) >= 4:
                lm_from = (8-int(highlight_move[1]), ord(highlight_move[0])-ord('a'))
                lm_to   = (8-int(highlight_move[3]), ord(highlight_move[2])-ord('a'))
            for row in range(8):
                for col in range(8):
                    light = (row + col) % 2 == 0
                    color = LIGHT_SQ if light else DARK_SQ
                    if lm_from and (row, col) == lm_from: color = LAST_FROM
                    elif lm_to and (row, col) == lm_to:  color = LAST_TO
                    x1, y1 = col * replay_size, row * replay_size
                    x2, y2 = x1 + replay_size, y1 + replay_size
                    replay_canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline='')
                    pc = replay_board.get(row, col)
                    if pc and pc != '.':
                        sym = UNICODE.get(pc, pc)
                        fg  = '#F5F5F5' if pc.isupper() else '#1A1A1A'
                        sh  = '#000000' if pc.isupper() else '#888888'
                        fsz = int(replay_size * 0.60)
                        cx, cy = x1 + replay_size//2, y1 + replay_size//2
                        replay_canvas.create_text(cx+1, cy+2, text=sym, font=('Segoe UI', fsz), fill=sh)
                        replay_canvas.create_text(cx,   cy,   text=sym, font=('Segoe UI', fsz), fill=fg)
            replay_canvas.create_rectangle(0, 0, replay_size*8, replay_size*8, outline='#555', width=1)
            _update_replay_opening()

        def update_move_label():
            total   = len(moves_list)
            current = current_move_index[0]
            if current == 0:
                move_label.config(text="Start position")
            elif current < total:
                side     = "White" if current % 2 == 1 else "Black"
                move_num = (current + 1) // 2 + 1
                move_label.config(text=f"Move {move_num}: {side} - {moves_list[current-1]}")
            else:
                move_label.config(text="End of game")

        def go_to_start():
            replay_board.reset(); current_move_index[0] = 0
            draw_replay_board(); update_move_label()

        def go_to_end():
            replay_board.reset()
            for move in moves_list:
                try: replay_board.apply_uci(move)
                except: break
            current_move_index[0] = len(moves_list)
            last_move = moves_list[-1] if moves_list else None
            draw_replay_board(last_move); update_move_label()

        def prev_move():
            if current_move_index[0] > 0:
                replay_board.reset(); current_move_index[0] -= 1
                for i in range(current_move_index[0]):
                    try: replay_board.apply_uci(moves_list[i])
                    except: break
                last_move = moves_list[current_move_index[0]-1] if current_move_index[0] > 0 else None
                draw_replay_board(last_move); update_move_label()

        def next_move():
            if current_move_index[0] < len(moves_list):
                try:
                    move = moves_list[current_move_index[0]]
                    replay_board.apply_uci(move)
                    current_move_index[0] += 1
                    draw_replay_board(move); update_move_label()
                except Exception as e:
                    messagebox.showerror("Error", f"Invalid move: {e}")

        move_label = tk.Label(left_frame, text="Start position", bg=BG, fg=ACCENT,
                              font=('Segoe UI', 11, 'bold'))
        move_label.pack(pady=10)

        nav_frame = tk.Frame(left_frame, bg=BG)
        nav_frame.pack(pady=10)
        for text, cmd in [("⏮ Start", go_to_start), ("◀ Prev", prev_move),
                          ("Next ▶", next_move), ("End ⏭", go_to_end)]:
            tk.Button(nav_frame, text=text, command=cmd, bg=BTN_BG, fg=TEXT,
                      font=('Segoe UI', 10, 'bold'), padx=15, pady=8,
                      cursor='hand2', relief='flat').pack(side='left', padx=5)

        def on_key(event):
            if   event.keysym == 'Left':  prev_move()
            elif event.keysym == 'Right': next_move()
            elif event.keysym == 'Home':  go_to_start()
            elif event.keysym == 'End':   go_to_end()
            elif event.keysym == 'Prior': load_game(-1)
            elif event.keysym == 'Next':  load_game(1)

        pgn_window.bind('<Left>',  on_key)
        pgn_window.bind('<Right>', on_key)
        pgn_window.bind('<Home>',  on_key)
        pgn_window.bind('<End>',   on_key)
        pgn_window.bind('<Prior>', on_key)
        pgn_window.bind('<Next>',  on_key)

        right_frame = tk.Frame(main_container, bg=BG)
        right_frame.pack(side='right', fill='both', expand=True)
        tk.Label(right_frame, text="PGN Notation", bg=BG, fg=ACCENT,
                 font=('Segoe UI', 12, 'bold')).pack(pady=(0, 5))
        text_frame = tk.Frame(right_frame, bg=LOG_BG, highlightthickness=1, highlightbackground='#333')
        text_frame.pack(fill='both', expand=True, pady=(0, 10))
        pgn_text = scrolledtext.ScrolledText(
            text_frame, bg=LOG_BG, fg=TEXT,
            font=('Consolas', 10), relief='flat',
            padx=10, pady=10, wrap='word')
        pgn_text.pack(fill='both', expand=True)
        pgn_text.insert('1.0', pgn)
        pgn_text.config(state='disabled')

        tk.Label(right_frame, text="⌨ Move: ←→ | Start/End: Home/End | Game: PgUp/PgDn",
                 bg=BG, fg="#666", font=('Segoe UI', 8)).pack(pady=5)

        btn_frame2 = tk.Frame(right_frame, bg=BG)
        btn_frame2.pack(fill='x', pady=(0, 10))

        def copy_pgn():
            pgn_window.clipboard_clear()
            pgn_window.clipboard_append(pgn)
            messagebox.showinfo("Copied", "PGN copied to clipboard!")

        def export_pgn():
            path = filedialog.asksaveasfilename(
                defaultextension=".pgn",
                filetypes=[("PGN", "*.pgn"), ("All", "*.*")],
                title="Export PGN")
            if path:
                with open(path, 'w') as f: f.write(pgn)
                messagebox.showinfo("Saved", f"PGN exported to:\n{path}")

        tk.Button(btn_frame2, text="Copy PGN", command=copy_pgn, bg=BTN_BG, fg=TEXT,
                  font=('Segoe UI', 10), padx=15, pady=8, cursor='hand2').pack(side='left', padx=5)
        tk.Button(btn_frame2, text="Export PGN", command=export_pgn, bg=BTN_BG, fg=TEXT,
                  font=('Segoe UI', 10), padx=15, pady=8, cursor='hand2').pack(side='left', padx=5)
        tk.Button(btn_frame2, text="Close", command=pgn_window.destroy, bg=BTN_BG, fg=TEXT,
                  font=('Segoe UI', 10), padx=15, pady=8, cursor='hand2').pack(side='right', padx=5)

        draw_replay_board()
        update_move_label()

    def _parse_pgn_moves(self, pgn):
        import re
        lines = pgn.split('\n')
        moves_text = []
        in_headers = True
        for line in lines:
            line = line.strip()
            if not line:
                in_headers = False
                continue
            if in_headers and line.startswith('['): continue
            moves_text.append(line)
        full_text = ' '.join(moves_text)
        for result in ['1-0', '0-1', '1/2-1/2', '*']:
            full_text = full_text.replace(result, '')
        full_text = re.sub(r'\d+\.', '', full_text)
        san_moves = full_text.split()
        temp_board = Board()
        uci_moves = []
        for san in san_moves:
            san = san.strip()
            if not san or san in ['1-0', '0-1', '1/2-1/2', '*']: continue
            try:
                legal = temp_board.legal_moves()
                for move in legal:
                    fr, fc, tr, tc, promo = move
                    test_san = temp_board._build_san(fr, fc, tr, tc, promo, legal)
                    if test_san.replace('+','').replace('#','') == san.replace('+','').replace('#',''):
                        uci = f"{chr(ord('a')+fc)}{8-fr}{chr(ord('a')+tc)}{8-tr}"
                        if promo: uci += promo
                        uci_moves.append(uci)
                        temp_board.apply_uci(uci)
                        break
            except Exception as e:
                print(f"Error parsing move {san}: {e}")
                continue
        return uci_moves

    # ─── Build UI ────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)
        lp = tk.Frame(self.root, bg=PANEL_BG, width=270)
        lp.grid(row=0, column=0, sticky='nsew', padx=(8,0), pady=8)
        lp.grid_propagate(False)
        self._build_left(lp)

        cp = tk.Frame(self.root, bg=BG)
        cp.grid(row=0, column=1, sticky='nsew', padx=8, pady=8)
        cp.columnconfigure(1, weight=1)
        cp.rowconfigure(0, weight=1)
        self._build_center(cp)

        rp = tk.Frame(self.root, bg=PANEL_BG, width=285)
        rp.grid(row=0, column=2, sticky='nsew', padx=(0,8), pady=8)
        rp.grid_propagate(False)
        self._build_right(rp)

    def _lbl(self,p,txt,sz=10,bold=False,fg=TEXT,bg=PANEL_BG,anchor='w'):
        return tk.Label(p,text=txt,bg=bg,fg=fg,anchor=anchor,
                        font=('Segoe UI',sz,'bold' if bold else 'normal'))

    def _btn(self,p,txt,cmd,accent=False,small=False):
        bg2=ACCENT if accent else BTN_BG
        b=tk.Button(p,text=txt,command=cmd,bg=bg2,fg=TEXT,
                    activebackground=BTN_HOV,activeforeground='white',
                    relief='flat',font=('Segoe UI',8 if small else 10,'normal'),
                    padx=4,pady=2 if small else 5,cursor='hand2',borderwidth=0)
        b.bind('<Enter>',lambda e:b.config(bg=BTN_HOV))
        b.bind('<Leave>',lambda e:b.config(bg=bg2))
        return b

    def _entry(self,p,var,fg=TEXT,width=None):
        kw=dict(textvariable=var,bg=LOG_BG,fg=fg,insertbackground=TEXT,
                font=('Consolas',8),relief='flat',highlightthickness=1,
                highlightcolor=ACCENT,highlightbackground='#333')
        if width: kw['width']=width
        return tk.Entry(p,**kw)

    def _build_left(self,p):
        tk.Label(p,text="ENGINE ARENA",bg=PANEL_BG,fg=ACCENT,
                 font=('Segoe UI',13,'bold')).pack(pady=(16,4))
        tk.Frame(p,bg=ACCENT,height=2).pack(fill='x',padx=10,pady=2)
        mode_frame = tk.Frame(p, bg=PANEL_BG)
        mode_frame.pack(fill='x', padx=10, pady=(8,4))
        tk.Label(mode_frame, text="PLAY MODE:", bg=PANEL_BG, fg=ACCENT,
                font=('Segoe UI', 9, 'bold')).pack(anchor='w')
        tk.Radiobutton(mode_frame, text="Engine vs Engine",
                       variable=self.play_mode, value="engine_vs_engine",
                       bg=PANEL_BG, fg=TEXT, selectcolor=BTN_BG,
                       activebackground=PANEL_BG, activeforeground=TEXT,
                       font=('Segoe UI', 9), command=self._on_mode_change).pack(anchor='w', pady=2)
        tk.Radiobutton(mode_frame, text="Play vs Engine",
                       variable=self.play_mode, value="human_vs_engine",
                       bg=PANEL_BG, fg=TEXT, selectcolor=BTN_BG,
                       activebackground=PANEL_BG, activeforeground=TEXT,
                       font=('Segoe UI', 9), command=self._on_mode_change).pack(anchor='w', pady=2)
        tk.Frame(p,bg='#2a2a4a',height=1).pack(fill='x',padx=10,pady=6)
        self.config_frame = tk.Frame(p, bg=PANEL_BG)
        self.config_frame.pack(fill='x', padx=10)
        self._build_config_ui()
        tk.Frame(p,bg='#2a2a4a',height=1).pack(fill='x',padx=10,pady=6)
        self._lbl(p,"⚙ SETTINGS",9,bold=True,fg=ACCENT).pack(fill='x',padx=10)
        for lbl,var,frm,to,inc,fmt in [
            ("Move time (ms):",self.movetime,100,60000,100,None),
            ("Move delay (s):", self.delay,  0.0,10.0,0.1,'%.1f'),
        ]:
            rf=tk.Frame(p,bg=PANEL_BG); rf.pack(fill='x',padx=10,pady=2)
            self._lbl(rf,lbl,8).pack(side='left')
            kw=dict(from_=frm,to=to,increment=inc,textvariable=var,width=7,
                    bg=LOG_BG,fg=TEXT,buttonbackground=BTN_BG,
                    font=('Consolas',8),relief='flat',insertbackground=TEXT)
            if fmt: kw['format']=fmt
            tk.Spinbox(rf,**kw).pack(side='right')
        tk.Frame(p,bg='#2a2a4a',height=1).pack(fill='x',padx=10,pady=6)
        for txt,cmd,acc in [
            ("▶  START GAME",     self._start_game,   True),
            ("⏸  PAUSE / RESUME", self._toggle_pause, False),
            ("⏹  STOP GAME",      self._stop_game,    False),
            ("↺  NEW GAME",       self._new_game,     False),
            ("⇅  FLIP BOARD",     self._flip_board,   False),
            ("💾  EXPORT PGN",    self._export_pgn,   False),
            ("🏆  RANKINGS",      self._show_rankings,False),   # ← NEW
            ("📊  STATISTICS",    self._show_statistics, False),
        ]:
            self._btn(p,txt,cmd,accent=acc).pack(fill='x',padx=10,pady=2)
        tk.Frame(p,bg='#2a2a4a',height=1).pack(fill='x',padx=10,pady=4)
        self._lbl(p,"Material balance",8,fg="#888").pack(fill='x',padx=10)
        self.mat_lbl=tk.Label(p,text="=",bg=PANEL_BG,fg=TEXT,
                              font=('Consolas',9),anchor='center')
        self.mat_lbl.pack(fill='x',padx=10)
        tk.Frame(p,bg='#2a2a4a',height=1).pack(fill='x',padx=10,pady=4)
        self.book_lbl = tk.Label(p, text="", bg=PANEL_BG, fg="#00BFFF",
                                  font=('Segoe UI', 7), anchor='w', wraplength=240)
        self.book_lbl.pack(fill='x', padx=10)
        self._btn(p, "📂  Load Openings CSV", self._browse_csv, small=True).pack(fill='x', padx=10, pady=2)
        self._update_book_lbl()
        tk.Frame(p,bg='#2a2a4a',height=1).pack(fill='x',padx=10,pady=4)
        self._lbl(p,"🔍 ANALYZER (Stockfish)",8,bold=True,fg=ACCENT).pack(fill='x',padx=10)
        self.analyzer_lbl = tk.Label(p, text="⚠ No analyzer", bg=PANEL_BG, fg="#FF8800",
                                      font=('Segoe UI', 7), anchor='w', wraplength=240)
        self.analyzer_lbl.pack(fill='x', padx=10)
        self._btn(p, "📂  Load Analyzer", self._browse_analyzer, small=True).pack(fill='x', padx=10, pady=2)

    def _build_config_ui(self):
        for widget in self.config_frame.winfo_children():
            widget.destroy()
        if self.play_mode.get() == "engine_vs_engine":
            for col,path_var,name_var,eval_var,dep_var,tag,color in [
                ('BLACK  ♚','e1_path','e1_name','e1_eval','e1_depth',1,"#C8C8C8"),
                ('WHITE  ♔','e2_path','e2_name','e2_eval','e2_depth',2,"#FFD700"),
            ]:
                pv=getattr(self,path_var); nv=getattr(self,name_var)
                ev=getattr(self,eval_var); dv=getattr(self,dep_var)
                self._lbl(self.config_frame,f"◈ {col}",9,bold=True,fg=color).pack(fill='x',pady=(10,2))
                rf=tk.Frame(self.config_frame,bg=PANEL_BG); rf.pack(fill='x',pady=2)
                self._entry(rf,pv).pack(side='left',fill='x',expand=True,ipady=4)
                self._btn(rf,"…",lambda t=tag:self._browse(t),small=True).pack(side='right',padx=(4,0))
                self._entry(self.config_frame,nv,fg=color).pack(fill='x',pady=2,ipady=3)
                ef=tk.Frame(self.config_frame,bg=INFO_BG); ef.pack(fill='x',pady=2)
                self._lbl(ef,"Eval:",8,bg=INFO_BG,fg="#888").pack(side='left',padx=4)
                tk.Label(ef,textvariable=ev,bg=INFO_BG,fg="#7FFF00",font=('Consolas',8)).pack(side='left')
                self._lbl(ef," D:",8,bg=INFO_BG,fg="#888").pack(side='left')
                tk.Label(ef,textvariable=dv,bg=INFO_BG,fg="#7FFF00",font=('Consolas',8)).pack(side='left')
                tk.Frame(self.config_frame,bg='#2a2a4a',height=1).pack(fill='x',pady=4)
        else:
            self._lbl(self.config_frame,"◈ PLAYER INFO",9,bold=True,fg="#00FF00").pack(fill='x',pady=(10,2))
            tk.Label(self.config_frame, text="Your Name:", bg=PANEL_BG, fg=TEXT,
                    font=('Segoe UI', 8)).pack(anchor='w', pady=(4,2))
            self._entry(self.config_frame, self.player_name).pack(fill='x',pady=2,ipady=3)
            tk.Label(self.config_frame, text="Play as:", bg=PANEL_BG, fg=TEXT,
                    font=('Segoe UI', 8)).pack(anchor='w', pady=(8,2))
            color_frame = tk.Frame(self.config_frame, bg=PANEL_BG)
            color_frame.pack(fill='x', pady=2)
            tk.Radiobutton(color_frame, text="⚪ White", variable=self.player_color, value="white",
                           bg=PANEL_BG, fg="#FFD700", selectcolor=BTN_BG,
                           font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(0,10))
            tk.Radiobutton(color_frame, text="⚫ Black", variable=self.player_color, value="black",
                           bg=PANEL_BG, fg="#C8C8C8", selectcolor=BTN_BG,
                           font=('Segoe UI', 9, 'bold')).pack(side='left')
            tk.Frame(self.config_frame,bg='#2a2a4a',height=1).pack(fill='x',pady=8)
            self._lbl(self.config_frame,"◈ OPPONENT ENGINE",9,bold=True,fg=ACCENT).pack(fill='x',pady=(4,2))
            rf=tk.Frame(self.config_frame,bg=PANEL_BG); rf.pack(fill='x',pady=2)
            self._entry(rf, self.e2_path).pack(side='left',fill='x',expand=True,ipady=4)
            self._btn(rf,"…",lambda:self._browse_opponent(),small=True).pack(side='right',padx=(4,0))
            self._entry(self.config_frame, self.e2_name, fg=ACCENT).pack(fill='x',pady=2,ipady=3)
            ef=tk.Frame(self.config_frame,bg=INFO_BG); ef.pack(fill='x',pady=2)
            self._lbl(ef,"Eval:",8,bg=INFO_BG,fg="#888").pack(side='left',padx=4)
            tk.Label(ef,textvariable=self.e2_eval,bg=INFO_BG,fg="#7FFF00",font=('Consolas',8)).pack(side='left')
            self._lbl(ef," D:",8,bg=INFO_BG,fg="#888").pack(side='left')
            tk.Label(ef,textvariable=self.e2_depth,bg=INFO_BG,fg="#7FFF00",font=('Consolas',8)).pack(side='left')
            tk.Frame(self.config_frame,bg='#2a2a4a',height=1).pack(fill='x',pady=4)

    def _on_mode_change(self):
        self._build_config_ui()
        if self.play_mode.get() == "human_vs_engine":
            self._status("Enter your name, choose color, and load an engine")
        else:
            self._status("Load two engine .exe files, then press ▶ Start")

    def _browse_opponent(self):
        path=filedialog.askopenfilename(title="Select Opponent Engine",
            filetypes=[("Executables","*.exe *.bin *"),("All","*.*")])
        if not path: return
        name=os.path.splitext(os.path.basename(path))[0]
        self.e2_path.set(path)
        self.e2_name.set(f"{name} (Engine)")

    def _build_center(self, p):
        self.status_lbl = tk.Label(p, text="", bg=BG, fg=ACCENT,
                                    font=('Segoe UI', 11, 'bold'), anchor='center')
        self.status_lbl.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 2))

        self.opening_lbl = tk.Label(
            p, textvariable=self.opening_var,
            bg="#0D1B2A", fg="#00BFFF",
            font=('Segoe UI', 10, 'italic'),
            anchor='center', pady=5, relief='flat',
            highlightthickness=1, highlightbackground="#003366", height=1)
        self.opening_lbl.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(0, 3))

        # ── Black player banner (frame with name + rank labels) ──────────────
        self.black_banner = tk.Frame(p, bg="#1a1a2a",
            highlightthickness=1, highlightbackground="#444444")
        self.black_banner.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(0, 3))
        self._black_name_lbl = tk.Label(self.black_banner, textvariable=self.e1_name,
            bg="#1a1a2a", fg="#C8C8C8", font=('Segoe UI', 11, 'bold'),
            anchor='center', pady=6)
        self._black_name_lbl.pack(side='left', expand=True)
        self._black_rank_lbl = tk.Label(self.black_banner, text="",
            bg="#1a1a2a", fg="#C8C8C8", font=('Segoe UI', 9),
            anchor='e', padx=8)
        self._black_rank_lbl.pack(side='right')

        board_row = tk.Frame(p, bg=BG)
        board_row.grid(row=3, column=0, columnspan=2)

        sz = self.sq_size
        eval_bar_frame = tk.Frame(board_row, bg=BG)
        eval_bar_frame.pack(side='left', padx=(0, 4))

        tk.Label(eval_bar_frame, text="♚", bg=BG, fg="#AAA",
                 font=('Segoe UI', 9)).pack(side='top')

        self.eval_canvas = tk.Canvas(eval_bar_frame, width=22, height=sz*8,
                                      bg="#2A2A2A", bd=0, highlightthickness=1,
                                      highlightbackground="#555")
        self.eval_canvas.pack(side='top')
        self.eval_canvas.bind('<Configure>', lambda e: self._draw_eval_bar())

        tk.Label(eval_bar_frame, text="♔", bg=BG, fg="#EEE",
                 font=('Segoe UI', 9)).pack(side='top')

        board_inner = tk.Frame(board_row, bg=BG)
        board_inner.pack(side='left')

        rf = tk.Frame(board_inner, bg=BG)
        rf.pack(side='left')
        self.rank_labels = []
        for i in range(8):
            l = tk.Label(rf, text="", bg=BG, fg="#777",
                         font=('Consolas', 9), width=2, anchor='e')
            l.pack(side='top', ipady=sz//2-7)
            self.rank_labels.append(l)

        bcol = tk.Frame(board_inner, bg=BG)
        bcol.pack(side='left')

        bs = sz * 8
        self.canvas = tk.Canvas(bcol, width=bs, height=bs, bg=BG, bd=0,
                                 highlightthickness=2, highlightcolor=ACCENT,
                                 highlightbackground='#333')
        self.canvas.pack()
        self.selected_square = None
        self.canvas.bind('<Button-1>', self._on_board_click)

        ff = tk.Frame(bcol, bg=BG)
        ff.pack(fill='x')
        self.file_labels = []
        for i in range(8):
            l = tk.Label(ff, text="", bg=BG, fg="#777",
                         font=('Consolas', 9), width=4, anchor='center')
            l.pack(side='left', ipadx=sz//2-8)
            self.file_labels.append(l)

        # ── White player banner (frame with name + rank labels) ──────────────
        self.white_banner = tk.Frame(p, bg="#1c2a1c",
            highlightthickness=1, highlightbackground="#555500")
        self.white_banner.grid(row=4, column=0, columnspan=2, sticky='ew', pady=(3, 0))
        self._white_name_lbl = tk.Label(self.white_banner, textvariable=self.e2_name,
            bg="#1c2a1c", fg="#FFD700", font=('Segoe UI', 11, 'bold'),
            anchor='center', pady=6)
        self._white_name_lbl.pack(side='left', expand=True)
        self._white_rank_lbl = tk.Label(self.white_banner, text="",
            bg="#1c2a1c", fg="#FFD700", font=('Segoe UI', 9),
            anchor='e', padx=8)
        self._white_rank_lbl.pack(side='right')

        self.check_lbl = tk.Label(p, text="", bg=BG, fg=CHECK_SQ,
                                   font=('Segoe UI', 10, 'bold'), anchor='center')
        self.check_lbl.grid(row=5, column=0, columnspan=2, sticky='ew', pady=(4, 0))

        self.quality_lbl = tk.Label(p, text="", bg=BG, fg=TEXT,
                                     font=('Segoe UI', 13, 'bold'), anchor='center')
        self.quality_lbl.grid(row=6, column=0, columnspan=2, sticky='ew', pady=(2, 0))

        self._update_coords()
        self.root.after(100, self._draw_eval_bar, 0)

    def _build_right(self,p):
        tk.Label(p,text="GAME LOG",bg=PANEL_BG,fg=ACCENT,
                 font=('Segoe UI',12,'bold')).pack(pady=(16,4))
        tk.Frame(p,bg=ACCENT,height=2).pack(fill='x',padx=10,pady=2)
        self._lbl(p,"Moves (SAN):",9,bold=True).pack(fill='x',padx=10,pady=(8,2))
        mf=tk.Frame(p,bg=LOG_BG,highlightthickness=1,highlightbackground='#333')
        mf.pack(fill='both',expand=True,padx=10,pady=(0,4))
        self.move_text=scrolledtext.ScrolledText(
            mf,bg=LOG_BG,fg="#DDD",font=('Consolas',9),state='disabled',
            relief='flat',padx=6,pady=6,insertbackground=TEXT,
            wrap='word',selectbackground=BTN_BG)
        self.move_text.pack(fill='both',expand=True)
        self.move_text.tag_config('num',   foreground="#555")
        self.move_text.tag_config('black', foreground="#CCCCCC")
        self.move_text.tag_config('white', foreground="#FFD700",font=('Consolas',9,'bold'))
        self.move_text.tag_config('chk',   foreground="#FF8800",font=('Consolas',9,'bold'))
        self.move_text.tag_config('result',foreground=ACCENT,   font=('Consolas',10,'bold'))
        self.move_text.tag_config('opening', foreground="#00BFFF", font=('Consolas',9,'italic'))
        tk.Frame(p,bg='#2a2a4a',height=1).pack(fill='x',padx=10,pady=2)
        self._lbl(p,"Engine Output:",9,bold=True).pack(fill='x',padx=10,pady=(4,2))
        ef=tk.Frame(p,bg=LOG_BG,highlightthickness=1,highlightbackground='#333')
        ef.pack(fill='both',expand=True,padx=10,pady=(0,4))
        self.eng_log=scrolledtext.ScrolledText(
            ef,bg=LOG_BG,fg="#0FA",font=('Consolas',8),state='disabled',
            relief='flat',padx=6,pady=6,insertbackground=TEXT,
            wrap='char',selectbackground=BTN_BG,height=7)
        self.eng_log.pack(fill='both',expand=True)
        self.eng_log.tag_config('W',foreground="#FFD700")
        self.eng_log.tag_config('B',foreground="#AAAAAA")
        self.eng_log.tag_config('E',foreground="#FF4444")
        self.info_lbl=tk.Label(p,text="",bg=PANEL_BG,fg="#666",
                                font=('Segoe UI',8),anchor='w',
                                wraplength=255,justify='left')
        self.info_lbl.pack(fill='x',padx=10,pady=(2,8))

    # ─── Drawing ─────────────────────────────────────────────────────────────

    def _update_coords(self):
        ranks=list(range(8,0,-1)) if not self.flipped else list(range(1,9))
        files=list('abcdefgh')   if not self.flipped else list('hgfedcba')
        for i,l in enumerate(self.rank_labels): l.config(text=str(ranks[i]))
        for i,l in enumerate(self.file_labels): l.config(text=files[i])

    def _draw_board(self):
        self.canvas.delete('all')
        sz=self.sq_size
        chk_king=self.board.find_king(self.board.turn) if self.board.in_check() else None
        lm_from=lm_to=None
        if self.last_move and len(self.last_move)>=4:
            lm_from=(8-int(self.last_move[1]),ord(self.last_move[0])-ord('a'))
            lm_to  =(8-int(self.last_move[3]),ord(self.last_move[2])-ord('a'))

        legal_dests = set()
        if self.play_mode.get() == "human_vs_engine" and self.selected_square:
            sr, sc = self.selected_square
            for move in self.board.legal_moves():
                if move[0] == sr and move[1] == sc:
                    legal_dests.add((move[2], move[3]))

        for row in range(8):
            for col in range(8):
                br = row if not self.flipped else (7 - row)
                bc = col if not self.flipped else (7 - col)
                light=(row+col)%2==0
                color=LIGHT_SQ if light else DARK_SQ
                if self.selected_square and (br, bc) == self.selected_square:
                    color = "#7FFF00"
                elif lm_from and (br,bc)==lm_from: color=LAST_FROM
                elif lm_to and (br,bc)==lm_to:   color=LAST_TO
                if chk_king and (br,bc)==chk_king: color=CHECK_SQ
                x1,y1=col*sz,row*sz; x2,y2=x1+sz,y1+sz
                self.canvas.create_rectangle(x1,y1,x2,y2,fill=color,outline='')
                pc=self.board.get(br,bc)
                if pc and pc!='.':
                    sym=UNICODE.get(pc,pc)
                    fg='#F5F5F5' if pc.isupper() else '#1A1A1A'
                    sh='#000000' if pc.isupper() else '#888888'
                    fsz=int(sz*0.60); cx,cy=x1+sz//2,y1+sz//2
                    self.canvas.create_text(cx+1,cy+2,text=sym,font=('Segoe UI',fsz),fill=sh)
                    self.canvas.create_text(cx,  cy,  text=sym,font=('Segoe UI',fsz),fill=fg)
                if (br, bc) in legal_dests:
                    cx, cy = x1 + sz//2, y1 + sz//2
                    if pc and pc != '.':
                        self.canvas.create_oval(x1+3, y1+3, x2-3, y2-3,
                                                outline="#00CC44", width=3, fill='')
                    else:
                        r = sz // 6
                        self.canvas.create_oval(cx-r, cy-r, cx+r, cy+r,
                                                fill="#00CC44", outline='')
        self.canvas.create_rectangle(0,0,sz*8,sz*8,outline='#555',width=1)
        if self.board.in_check():
            side="White" if self.board.turn=='w' else "Black"
            self.check_lbl.config(text=f"⚠  {side} is in CHECK!")
        else:
            self.check_lbl.config(text="")
        self._update_banners()

    def _on_board_click(self, event):
        if self.play_mode.get() != "human_vs_engine": return
        if not self.game_running: return
        if self._engine_thinking: return

        sz = self.sq_size
        col = event.x // sz
        row = event.y // sz
        if not (0 <= row < 8 and 0 <= col < 8): return

        br, bc = (7 - row, 7 - col) if self.flipped else (row, col)
        human_color = self.player_color.get()

        with self.board_lock:
            turn_ok = (human_color == "white" and self.board.turn == 'w') or \
                      (human_color == "black" and self.board.turn == 'b')
            if not turn_ok:
                return
            piece_at_click = self.board.get(br, bc)
            current_turn   = self.board.turn

        is_own_piece = (
            piece_at_click and piece_at_click != '.' and
            ((human_color == "white" and piece_at_click.isupper()) or
             (human_color == "black" and piece_at_click.islower()))
        )

        if self.selected_square is None:
            if is_own_piece:
                self.selected_square = (br, bc)
                self._draw_board()
            return

        from_r, from_c = self.selected_square

        if (br, bc) == (from_r, from_c):
            self.selected_square = None
            self._draw_board()
            return

        if is_own_piece:
            self.selected_square = (br, bc)
            self._draw_board()
            return

        to_r, to_c = br, bc

        legal_moves = self.board.legal_moves()
        matching_moves = [m for m in legal_moves
                          if m[0] == from_r and m[1] == from_c
                          and m[2] == to_r   and m[3] == to_c]

        if not matching_moves:
            self.selected_square = None
            self._draw_board()
            return

        self.selected_square = None
        self._draw_board()

        if any(m[4] for m in matching_moves):
            promo_piece = ask_promotion(self.root, 'w' if human_color == 'white' else 'b')
            promo_piece = promo_piece.lower()
            move_tuple  = next((m for m in matching_moves if m[4] == promo_piece), None)
            if move_tuple is None:
                move_tuple = next((m for m in matching_moves if m[4] == 'q'), matching_moves[0])
            uci = (f"{chr(ord('a')+from_c)}{8-from_r}"
                   f"{chr(ord('a')+to_c)}{8-to_r}{move_tuple[4]}")
        else:
            uci = f"{chr(ord('a')+from_c)}{8-from_r}{chr(ord('a')+to_c)}{8-to_r}"

        with self.board_lock:
            still_ok = (human_color == "white" and self.board.turn == 'w') or \
                       (human_color == "black" and self.board.turn == 'b')
            if not still_ok:
                return

            moves_before = self.board.uci_moves_str()
            was_white    = (self.board.turn == 'w')

            try:
                san, cap = self.board.apply_uci(uci)
            except ValueError as e:
                self._draw_board()
                self.root.after(0, lambda: messagebox.showerror("Error", f"Invalid move: {e}"))
                return

            moves_after = self.board.uci_moves_str()
            self.last_move = uci
            move_num = (len(self.board.move_history) + 1) // 2
            over, result, reason, winner_color = self.board.game_result()

        self._draw_board()
        self._update_info()
        self._refresh_opening()
        self.root.after(0, self._refresh_banners)

        self._trigger_quality_analysis(moves_before, moves_after, was_white, san)

        if human_color == "black":
            self._pending_b = (move_num, san)
        else:
            if self._pending_b:
                n, b_san = self._pending_b
                self._log_move(n, b_san, san)
                self._pending_b = None
            else:
                self._log_move(move_num, san, None)

        if over:
            winner_name = None
            if winner_color == 'white':
                winner_name = self.player_name.get() if human_color == 'white' else self.e2_name.get()
            elif winner_color == 'black':
                winner_name = self.player_name.get() if human_color == 'black' else self.e2_name.get()
            self._end_game(result, reason, winner_name)
        else:
            self._start_engine_turn()

    def _update_banners(self):
        if self.board.turn=='b':
            self.black_banner.config(bg="#252538", highlightbackground=ACCENT, highlightthickness=2)
            self._black_name_lbl.config(bg="#252538")
            self._black_rank_lbl.config(bg="#252538")
            self.white_banner.config(bg="#1c2a1c", highlightbackground="#555500", highlightthickness=1)
            self._white_name_lbl.config(bg="#1c2a1c")
            self._white_rank_lbl.config(bg="#1c2a1c")
        else:
            self.white_banner.config(bg="#2a2a1a", highlightbackground=ACCENT, highlightthickness=2)
            self._white_name_lbl.config(bg="#2a2a1a")
            self._white_rank_lbl.config(bg="#2a2a1a")
            self.black_banner.config(bg="#1a1a2a", highlightbackground="#444444", highlightthickness=1)
            self._black_name_lbl.config(bg="#1a1a2a")
            self._black_rank_lbl.config(bg="#1a1a2a")

    def _refresh_banners(self):
        """Fetch current Elo + rank number for both players and update banners."""
        try:
            games_raw = self._get_all_games_for_elo()
            elo_ratings = compute_elo_ratings(games_raw)

            # Build sorted leaderboard for rank numbers
            sorted_engines = sorted(elo_ratings.items(), key=lambda x: x[1], reverse=True)
            rank_map = {name: i + 1 for i, (name, _) in enumerate(sorted_engines)}
            total = len(sorted_engines)

            mode = self.play_mode.get()

            if mode == "human_vs_engine":
                if self.player_color.get() == "white":
                    white_raw = self.player_name.get()
                    black_raw = self.e2_name.get()
                else:
                    white_raw = self.e2_name.get()
                    black_raw = self.player_name.get()
            else:
                black_raw = self.e1_name.get()
                white_raw = self.e2_name.get()

            black_key = normalize_engine_name(black_raw)
            white_key = normalize_engine_name(white_raw)

            b_elo = elo_ratings.get(black_key)
            w_elo = elo_ratings.get(white_key)

            if b_elo is not None:
                tier_lbl, tier_col = get_tier(b_elo)
                b_rank = rank_map.get(black_key, "?")
                self._black_rank_lbl.config(
                    text=f"#{b_rank}/{total}  {tier_lbl}  •  {b_elo} Elo",
                    fg=tier_col)
            else:
                self._black_rank_lbl.config(text="Unranked", fg="#555")

            if w_elo is not None:
                tier_lbl, tier_col = get_tier(w_elo)
                w_rank = rank_map.get(white_key, "?")
                self._white_rank_lbl.config(
                    text=f"#{w_rank}/{total}  {tier_lbl}  •  {w_elo} Elo",
                    fg=tier_col)
            else:
                self._white_rank_lbl.config(text="Unranked", fg="#555")

        except Exception as e:
            print(f"[_refresh_banners] {e}")

    # ─── Logging helpers ──────────────────────────────────────────────────────

    def _status(self,msg): self.status_lbl.config(text=msg)

    def _log_move(self, num, b_san, w_san=None):
        self.move_text.config(state='normal')
        lines = int(self.move_text.index('end-1c').split('.')[0])
        if lines > 500: self.move_text.delete('1.0', '100.0')
        self.move_text.insert('end',f"{num}.",'num')
        tb='chk' if ('+' in b_san or '#' in b_san) else 'black'
        self.move_text.insert('end',f" {b_san} ",tb)
        if w_san:
            tw='chk' if ('+' in w_san or '#' in w_san) else 'white'
            self.move_text.insert('end',f"{w_san}  ",tw)
        self.move_text.see('end'); self.move_text.config(state='disabled')

    def _log_result(self,txt):
        self.move_text.config(state='normal')
        self.move_text.insert('end',f"\n{txt}\n",'result')
        self.move_text.see('end'); self.move_text.config(state='disabled')

    def _log_eng(self,txt,side='W'):
        self.eng_log.config(state='normal')
        self.eng_log.insert('end',txt+'\n',side)
        lines=int(self.eng_log.index('end-1c').split('.')[0])
        if lines>700: self.eng_log.delete('1.0','150.0')
        self.eng_log.see('end'); self.eng_log.config(state='disabled')

    def _update_info(self):
        wm,bm=self.board.material()
        d=wm-bm
        self.mat_lbl.config(
            text="Equal" if d==0 else (f"White +{d}" if d>0 else f"Black +{-d}"))
        t="Black" if self.board.turn=='b' else "White"
        self.info_lbl.config(
            text=f"Move {self.board.fullmove} | {t} to move | "
                 f"50-move: {self.board.halfmove}/100 | "
                 f"Plies: {len(self.board.move_history)}")

    def _show_eval(self, engine, side):
        if not engine: return
        info=engine.last_info
        sc=info.get('score'); st=info.get('score_type','cp'); dp=info.get('depth')
        if sc is None: ev='—'
        elif st=='mate': ev=f"M{sc}"
        else:
            cp=sc if side=='w' else -sc
            ev=f"{cp/100:+.2f}"
        ds=str(dp) if dp else '—'
        if side=='b':
            self.e1_eval.set(ev); self.e1_depth.set(ds)
        else:
            self.e2_eval.set(ev); self.e2_depth.set(ds)
        if sc is not None:
            if st == 'mate':
                cp_bar = 30000 if sc > 0 else -30000
            else:
                cp_bar = sc
            if side == 'b':
                cp_bar = -cp_bar
            self._eval_bar_cp = cp_bar
            self.root.after(0, self._draw_eval_bar, cp_bar)

    # ─── Engine management ────────────────────────────────────────────────────

    def _browse(self, which):
        path=filedialog.askopenfilename(title=f"Select Engine {which}",
            filetypes=[("Executables","*.exe *.bin *"),("All","*.*")])
        if not path: return
        name=os.path.splitext(os.path.basename(path))[0]
        if which==1:
            self.e1_path.set(path); self.e1_name.set(f"{name} (Black)")
        else:
            self.e2_path.set(path); self.e2_name.set(f"{name} (White)")

    def _load_engines(self):
        p1=self.e1_path.get().strip(); p2=self.e2_path.get().strip()
        errs=[]
        for path,name_var,n,tag in [
            (p1,self.e1_name,1,'B'),(p2,self.e2_name,2,'W')
        ]:
            try:
                self.root.after(0, self._status, f"Loading {name_var.get()}…")
                eng=UCIEngine(path,name_var.get())
                eng.start()
                if n==1: self.engine1=eng
                else:    self.engine2=eng
                self.root.after(0,self._log_eng,f"✓ {name_var.get()} ready",tag)
            except Exception as e:
                errs.append(f"Engine {n}: {e}")
        if errs:
            msg = '\n'.join(errs)
            self.root.after(0, lambda: messagebox.showerror("Engine Error", msg))
            return False
        return True

    def _load_opponent_engine(self):
        path = self.e2_path.get().strip()
        if sys.platform != 'win32' and not os.access(path, os.X_OK):
            self.root.after(0, lambda: messagebox.showerror(
                "Error", f"Engine is not executable:\n{path}"))
            return False
        try:
            self.root.after(0, self._status, f"Loading {self.e2_name.get()}…")
            eng = UCIEngine(path, self.e2_name.get())
            eng.start()
            self.engine2 = eng
            self.root.after(0, self._log_eng, f"✓ {self.e2_name.get()} ready", 'W')
            return True
        except Exception as e:
            err = str(e)
            self.root.after(0, lambda: messagebox.showerror("Engine Error", err))
            return False

    def _start_engine_turn(self):
        if not self.game_running: return
        self._engine_thinking = True
        self.game_thread = threading.Thread(target=self._engine_move_thread, daemon=True)
        self.game_thread.start()

    def _engine_move_thread(self):
        try:
            self._do_engine_move()
        finally:
            self._engine_thinking = False

    def _do_engine_move(self):
        while self.game_paused and self.game_running:
            time.sleep(0.1)
        if not self.game_running: return

        engine_color = 'black' if self.player_color.get() == 'white' else 'white'
        engine_turn  = 'b' if engine_color == 'black' else 'w'
        engine = self.engine2
        name   = self.e2_name.get()
        side   = engine_turn
        tag    = 'B' if side == 'b' else 'W'
        sym    = '♚' if side == 'b' else '♔'

        self.root.after(0, self._status, f"{sym} {name} thinking…")

        if not engine or not engine.alive:
            winner_name = self.player_name.get()
            res = '1-0' if self.player_color.get() == 'white' else '0-1'
            self.root.after(0, lambda: self._end_game(res, f"{name}'s engine process died", winner_name))
            return

        with self.board_lock:
            if self.board.turn != engine_turn: return
            mvs = self.board.uci_moves_str()

        moves_before = mvs
        was_white_moving = (engine_turn == 'w')

        movetime = self.movetime.get()
        def on_info(info):
            self.root.after(0, lambda: self._show_eval(engine, side))

        try:
            uci = engine.get_best_move(mvs, movetime, on_info=on_info)
        except Exception as ex:
            self.root.after(0, self._log_eng, f"[ERR] {ex}", tag)
            uci = None

        if not self.game_running: return

        if not uci:
            winner_name = self.player_name.get()
            res = '1-0' if self.player_color.get() == 'white' else '0-1'
            self.root.after(0, lambda: self._end_game(res, f"{name} returned no move", winner_name))
            return

        self.root.after(0, self._log_eng, f"[{tag}] bestmove {uci}", tag)

        with self.board_lock:
            if not self.game_running: return
            if self.board.turn != engine_turn: return
            try:
                san, cap = self.board.apply_uci(uci)
            except ValueError as ex:
                self.root.after(0, self._log_eng, f"[ILLEGAL] {ex}", 'E')
                winner_name = self.player_name.get()
                res = '1-0' if self.player_color.get() == 'white' else '0-1'
                self.root.after(0, lambda: self._end_game(
                    res, f"Illegal move by {name}: {uci}", winner_name))
                return

            moves_after = self.board.uci_moves_str()
            self.last_move = uci
            move_num = (len(self.board.move_history) + 1) // 2
            over, result, reason, winner_color = self.board.game_result()
            in_check = self.board.in_check()

        self.root.after(0, self._draw_board)
        self.root.after(0, self._update_info)
        self.root.after(0, self._refresh_opening)
        self.root.after(0, self._refresh_banners)

        self._trigger_quality_analysis(moves_before, moves_after, was_white_moving, san)

        def _log():
            if engine_color == 'black':
                self._pending_b = (move_num, san)
            else:
                if self._pending_b:
                    n, b_san = self._pending_b
                    self._log_move(n, b_san, san)
                    self._pending_b = None
                else:
                    self._log_move(move_num, san, None)
        self.root.after(0, _log)

        if over:
            winner_name = None
            if winner_color == 'white':
                winner_name = self.player_name.get() if self.player_color.get() == 'white' else name
            elif winner_color == 'black':
                winner_name = self.player_name.get() if self.player_color.get() == 'black' else name
            self.root.after(0, lambda: self._end_game(result, reason, winner_name))
            return

        player_sym = '♔' if self.player_color.get() == 'white' else '♚'
        if in_check:
            self.root.after(0, self._status,
                            f"⚠ CHECK! {player_sym} Your turn — you must get out of check!")
        else:
            self.root.after(0, self._status,
                            f"{player_sym} Your turn — click a piece to move")

    # ─── Game control ─────────────────────────────────────────────────────────

    def _start_game(self):
        if self.game_running:
            messagebox.showinfo("Running","Stop the current game first."); return
        if self.play_mode.get() == "human_vs_engine":
            if not self.player_name.get().strip():
                messagebox.showerror("Error", "Please enter your name."); return
            if not self.e2_path.get().strip():
                messagebox.showerror("Error", "Please select an opponent engine."); return
        else:
            if not self.e1_path.get().strip() or not self.e2_path.get().strip():
                messagebox.showerror("Error", "Please select both engines."); return

        if self.play_mode.get() == "human_vs_engine":
            path = self.e2_path.get().strip()
            if not os.path.isfile(path):
                messagebox.showerror("Error", f"Engine not found:\n{path}"); return
        else:
            for n, path in [(1, self.e1_path.get().strip()), (2, self.e2_path.get().strip())]:
                if not os.path.isfile(path):
                    messagebox.showerror("Error", f"Engine {n} not found:\n{path}"); return

        for w in (self.move_text,self.eng_log):
            w.config(state='normal'); w.delete('1.0','end'); w.config(state='disabled')
        self.board.reset(); self.last_move=None; self._pending_b=None
        self.selected_square = None
        self._engine_thinking = False
        self._last_eval_cp = None
        self._last_quality = None
        self._move_qualities = []
        self._eval_bar_cp = 0
        self._reset_opening()
        self._draw_board(); self._update_info()
        self.root.after(200, self._refresh_banners)
        self.root.after(100, self._draw_eval_bar, 0)
        if hasattr(self, 'quality_lbl'):
            self.quality_lbl.config(text="")
        for v in (self.e1_eval,self.e2_eval,self.e1_depth,self.e2_depth): v.set('—')
        self.mat_lbl.config(text="=")
        self.game_date=datetime.now().strftime("%Y.%m.%d")
        self.game_start_time = time.time()

        self._status("⏳ Loading engine(s)…")

        mode = self.play_mode.get()
        def _load_and_start():
            if mode == "human_vs_engine":
                ok = self._load_opponent_engine()
                if not ok: return
                base = self.e2_name.get().split('(')[0].strip()
                color_label = "Black" if self.player_color.get() == "white" else "White"
                self.root.after(0, self.e2_name.set, f"{base} ({color_label})")
                self.game_running = True; self.game_paused = False; self.game_result = '*'
                if self.player_color.get() == "black":
                    self.root.after(0, self._start_engine_turn)
                else:
                    self.root.after(0, self._status, "♔ Your turn — click a piece to move")
            else:
                ok = self._load_engines()
                if not ok: return
                self.game_running=True; self.game_paused=False; self.game_result='*'
                t = threading.Thread(target=self._game_loop, daemon=True)
                t.start()

        threading.Thread(target=_load_and_start, daemon=True).start()

    def _toggle_pause(self):
        if not self.game_running: return
        self.game_paused=not self.game_paused
        self._status("⏸ PAUSED" if self.game_paused else "▶ Resuming…")

    def _stop_game(self):
        if not self.game_running:
            self._status("⏹ No game running.")
            return

        was_paused = self.game_paused
        self.game_paused = True

        mode = self.play_mode.get()
        if mode == "human_vs_engine":
            if self.player_color.get() == "white":
                white_name = self.player_name.get() or "Player"
                black_name = self.e2_name.get()
            else:
                white_name = self.e2_name.get()
                black_name = self.player_name.get() or "Player"
        else:
            white_name = self.e2_name.get()
            black_name = self.e1_name.get()

        result, reason = ask_stop_result(self.root, white_name, black_name)

        if result is None:
            self.game_paused = was_paused
            return

        winner_name = None
        if result == "1-0":
            winner_name = white_name
        elif result == "0-1":
            winner_name = black_name

        self.game_running = False
        self.game_paused  = False
        self._engine_thinking = False

        def _bg():
            try: self._kill_engines()
            except: pass
        threading.Thread(target=_bg, daemon=True).start()

        if self.board.move_history or result != '*':
            duration = int(time.time() - self.game_start_time) if hasattr(self, 'game_start_time') else 0
            pgn = build_pgn(
                white_name, black_name,
                self.board.move_history, result,
                self.game_date or datetime.now().strftime("%Y.%m.%d"),
                opening_name=self.current_opening_name)
            self._save_game_to_db(white_name, black_name, result, reason, pgn, duration)
            self._log_result(f"{result}  —  {reason}")

        if result == '*':
            self._status("⏹ Game aborted — no result recorded")
        else:
            clean_winner = normalize_engine_name(winner_name) if winner_name else None
            if clean_winner:
                self._status(f"⏹ Stopped — {clean_winner} wins ({result})")
            else:
                self._status(f"⏹ Stopped — {result}  ({reason})")

        if result != '*':
            self.game_result = result
            self.root.after(100, lambda: self._show_game_over_dialog(result, reason, winner_name))

    def _new_game(self):
        self.game_running=False; self.game_paused=False
        self._engine_thinking = False
        def _bg_stop():
            try: self._kill_engines()
            except: pass
        threading.Thread(target=_bg_stop, daemon=True).start()
        self.board.reset(); self.last_move=None; self._pending_b=None
        self.selected_square = None
        self._engine_thinking = False
        self._last_eval_cp = None
        self._last_quality = None
        self._move_qualities = []
        self._eval_bar_cp = 0
        self.board_lock = threading.Lock()
        self._reset_opening()
        for w in (self.move_text,self.eng_log):
            w.config(state='normal'); w.delete('1.0','end'); w.config(state='disabled')
        self._draw_board(); self._update_info()
        self.root.after(100, self._draw_eval_bar, 0)
        if hasattr(self, 'quality_lbl'):
            self.quality_lbl.config(text="")
        self.check_lbl.config(text=""); self.mat_lbl.config(text="=")
        for v in (self.e1_eval,self.e2_eval,self.e1_depth,self.e2_depth): v.set('—')
        self._status("New game — load engines and press ▶ Start")

    def _flip_board(self):
        self.flipped=not self.flipped; self._update_coords(); self._draw_board()

    def _kill_engines(self):
        for e in (self.engine1,self.engine2):
            if e: e.stop()

    def _export_pgn(self):
        if not self.board.move_history:
            messagebox.showinfo("PGN","No moves to export yet."); return
        pgn=build_pgn(self.e2_name.get(),self.e1_name.get(),
                      self.board.move_history,self.game_result or '*',
                      self.game_date or datetime.now().strftime("%Y.%m.%d"),
                      opening_name=self.current_opening_name)
        path=filedialog.asksaveasfilename(defaultextension=".pgn",
            filetypes=[("PGN","*.pgn"),("All","*.*")], title="Save PGN")
        if path:
            with open(path,'w') as f: f.write(pgn)
            messagebox.showinfo("Saved",f"PGN saved:\n{path}")

    # ─── Game over dialog ─────────────────────────────────────────────────────

    def _show_game_over_dialog(self, result, reason, winner_name):
        dialog = tk.Toplevel(self.root)
        dialog.title("Game Over")
        dialog.configure(bg=BG)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.update_idletasks()
        w = 480; h = 660
        x = (dialog.winfo_screenwidth() // 2) - (w // 2)
        y = (dialog.winfo_screenheight() // 2) - (h // 2)
        dialog.geometry(f'{w}x{h}+{x}+{y}')
        main_frame = tk.Frame(dialog, bg=BG)
        main_frame.pack(fill='both', expand=True, padx=20, pady=20)
        is_draw = result == '1/2-1/2'
        if winner_name and not is_draw:
            icon = "🏆"; title_text = "VICTORY!"; title_color = ACCENT
        else:
            icon = "🤝"; title_text = "DRAW"; title_color = "#FFD700"; winner_name = None
        tk.Label(main_frame, text=icon, bg=BG, font=('Segoe UI', 48)).pack(pady=(10, 5))
        tk.Label(main_frame, text=title_text, bg=BG, fg=title_color,
                 font=('Segoe UI', 24, 'bold')).pack()
        if winner_name:
            clean_name = normalize_engine_name(winner_name)
            # Show Elo after win
            games_raw = self._get_all_games_for_elo()
            elo_ratings = compute_elo_ratings(games_raw)
            winner_elo = elo_ratings.get(clean_name)
            tier_lbl, tier_col = get_tier(winner_elo) if winner_elo else ("", TEXT)
            tk.Label(main_frame, text=clean_name, bg=BG, fg=TEXT,
                     font=('Segoe UI', 20, 'bold')).pack(pady=5)
            if winner_elo:
                tk.Label(main_frame, text=f"Elo: {winner_elo}  ·  {tier_lbl}",
                         bg=BG, fg=tier_col, font=('Segoe UI', 11)).pack(pady=2)
        tk.Frame(main_frame, bg=ACCENT, height=2).pack(fill='x', pady=10)
        tk.Label(main_frame, text=f"Result: {result}", bg=BG, fg="#AAA",
                 font=('Segoe UI', 12)).pack(pady=2)
        tk.Label(main_frame, text=reason, bg=BG, fg="#888",
                 font=('Segoe UI', 11)).pack(pady=2)
        if self.current_opening_name:
            tk.Label(main_frame, text=f"📖  {self.current_opening_name}",
                     bg=BG, fg="#00BFFF", font=('Segoe UI', 10, 'italic')).pack(pady=4)
        if self._move_qualities:
            counts = {}
            for _, _, q in self._move_qualities:
                counts[q] = counts.get(q, 0) + 1
            summary = "  ".join(
                f"{q}: {n}"
                for q, n in sorted(counts.items(),
                                   key=lambda x: list(QUALITY_COLORS.keys()).index(x[0])
                                   if x[0] in QUALITY_COLORS else 99)
                if q not in ("Good",)
            )
            if summary:
                tk.Label(main_frame, text=f"Move quality: {summary}", bg=BG, fg="#AAA",
                         font=('Segoe UI', 9)).pack(pady=2)

        btn_frame = tk.Frame(dialog, bg=BG)
        btn_frame.pack(fill='x', padx=20, pady=(0, 20))
        def close_dialog(): dialog.destroy()
        def new_game_and_close(): dialog.destroy(); self._new_game()
        def export_and_close(): dialog.destroy(); self._export_pgn()
        def rankings_and_close(): dialog.destroy(); self._show_rankings()
        for text, cmd, accent in [
            ("New Game",  new_game_and_close,  True),
            ("🏆 Rankings", rankings_and_close, False),
            ("Export PGN", export_and_close,   False),
            ("Close",      close_dialog,        False)
        ]:
            bg_color = ACCENT if accent else BTN_BG
            btn = tk.Button(btn_frame, text=text, command=cmd, bg=bg_color, fg=TEXT,
                            activebackground=BTN_HOV, activeforeground='white',
                            relief='flat', font=('Segoe UI', 10, 'bold' if accent else 'normal'),
                            padx=14, pady=10, cursor='hand2', borderwidth=0)
            btn.pack(side='left', expand=True, fill='x', padx=4)
            btn.bind('<Enter>', lambda e, b=btn, bg=bg_color: b.config(bg=BTN_HOV))
            btn.bind('<Leave>', lambda e, b=btn, bg=bg_color: b.config(bg=bg_color))
        dialog.bind('<Escape>', lambda e: close_dialog())

    # ─── Engine-vs-Engine game loop ───────────────────────────────────────────

    def _game_loop(self):
        movetime=self.movetime.get()
        delay   =self.delay.get()
        while self.game_running:
            while self.game_paused and self.game_running: time.sleep(0.1)
            if not self.game_running: break
            over, result, reason, winner_color = self.board.game_result()
            if over:
                winner_name = None
                if winner_color == 'white': winner_name = self.e2_name.get()
                elif winner_color == 'black': winner_name = self.e1_name.get()
                self._end_game(result, reason, winner_name); return
            is_b   = self.board.turn=='b'
            engine = self.engine1 if is_b else self.engine2
            name   = (self.e1_name if is_b else self.e2_name).get()
            side   = 'b' if is_b else 'w'
            tag    = 'B' if is_b else 'W'
            self.root.after(0,self._status,f"{'♚' if is_b else '♔'} {name} thinking…")
            if not engine or not engine.alive:
                winner_color = 'white' if is_b else 'black'
                winner_name = self.e2_name.get() if winner_color == 'white' else self.e1_name.get()
                self._end_game('0-1' if is_b else '1-0',
                               f"{name}'s engine process died", winner_name); return

            moves_before = self.board.uci_moves_str()
            was_white_moving = not is_b

            mvs=self.board.uci_moves_str()
            def on_info(info, _side=side, _eng=engine):
                self.root.after(0, lambda: self._show_eval(_eng, _side))
            try:
                uci=engine.get_best_move(mvs,movetime,on_info=on_info)
            except Exception as ex:
                self.root.after(0,self._log_eng,f"[ERR] {ex}",tag); uci=None
            if not self.game_running: break
            if not uci:
                winner_color = 'white' if is_b else 'black'
                winner_name = self.e2_name.get() if winner_color == 'white' else self.e1_name.get()
                self._end_game('0-1' if is_b else '1-0',
                               f"{name} returned no move", winner_name); return
            self.root.after(0,self._log_eng,f"[{tag}] bestmove {uci}",tag)
            try:
                san,cap=self.board.apply_uci(uci)
            except ValueError as ex:
                self.root.after(0,self._log_eng,f"[ILLEGAL] {ex}",'E')
                winner_color = 'white' if is_b else 'black'
                winner_name = self.e2_name.get() if winner_color == 'white' else self.e1_name.get()
                self._end_game('0-1' if is_b else '1-0',
                               f"Illegal move by {name}: {uci}", winner_name); return

            moves_after = self.board.uci_moves_str()
            self.last_move=uci
            move_num=(len(self.board.move_history)+1)//2
            self.root.after(0,self._draw_board)
            self.root.after(0,self._update_info)
            self.root.after(0,self._refresh_opening)
            self.root.after(0,self._refresh_banners)

            self._trigger_quality_analysis(moves_before, moves_after, was_white_moving, san)

            if is_b:
                self._pending_b=(move_num,san)
            else:
                if self._pending_b:
                    n,b_san=self._pending_b
                    self.root.after(0,self._log_move,n,b_san,san)
                    self._pending_b=None
            time.sleep(max(0.05,delay))
        if self._pending_b:
            n,b_san=self._pending_b
            self.root.after(0,self._log_move,n,b_san,None)
            self._pending_b=None

    def _end_game(self, result, reason, winner_name=None):
        self.game_running = False
        self.game_result = result
        self._engine_thinking = False
        self._kill_engines()
        duration_seconds = int(time.time() - self.game_start_time) if hasattr(self, 'game_start_time') else 0
        if self.play_mode.get() == "human_vs_engine":
            if self.player_color.get() == "white":
                white_name = self.player_name.get()
                black_name = self.e2_name.get()
            else:
                white_name = self.e2_name.get()
                black_name = self.player_name.get()
        else:
            white_name = self.e2_name.get()
            black_name = self.e1_name.get()
        pgn = build_pgn(white_name, black_name, self.board.move_history, result,
                        self.game_date or datetime.now().strftime("%Y.%m.%d"),
                        opening_name=self.current_opening_name)
        self._save_game_to_db(white_name, black_name, result, reason, pgn, duration_seconds)
        if winner_name:
            msg = f"🏆 {winner_name} WINS!\n{reason}"
            status_msg = f"🏁 {normalize_engine_name(winner_name)} wins by {reason}"
        else:
            msg = f"Game ended: {result}\n{reason}"
            status_msg = f"🏁 {result} — {reason}"
        self.root.after(0, self._status, status_msg)
        self.root.after(0, self._log_result, f"{result}  —  {reason}")
        self.root.after(150, self._refresh_banners)
        self.root.after(0, lambda: self._show_game_over_dialog(result, reason, winner_name))


# ═══════════════════════════════════════════════════════════

def main():
    root = tk.Tk()
    try: root.iconbitmap("")
    except Exception: pass
    LoadingScreen(root)
    root.mainloop()

if __name__ == "__main__":
    main()