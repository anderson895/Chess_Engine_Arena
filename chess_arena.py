"""
Chess Engine Arena — Enhanced Edition (Fixed)
- Engine 1 = BLACK pieces, Engine 2 = WHITE pieces
- Board default: White side at bottom (standard orientation)
- White still moves first per chess rules (UCI standard)
- Engine names displayed on the board
- Beautiful game-over dialog with winner's name
Full UCI engine support, complete chess rule accuracy:
  • Legal move generation (all pieces, castling, en passant, promotion)
  • Check / checkmate / stalemate detection
  • Threefold repetition, 50-move rule, insufficient material detection
  • Standard algebraic notation (SAN) in move log
  • Robust UCI communication with eval/depth display per engine
  • Material count tracker
  • PGN export
  • FIXED: Persistent SQLite database (no more resets)
  • NEW: Search in Statistics and Game History windows
"""

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import subprocess
import threading
import time
import queue
import os
import sys
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
    """
    Return a STABLE, persistent path for the SQLite database.
    Uses the user's home directory so it survives restarts and
    never resets even if the script is moved or run from a different cwd.
    """
    home = os.path.expanduser("~")
    db_dir = os.path.join(home, ".chess_arena")
    os.makedirs(db_dir, exist_ok=True)
    return os.path.join(db_dir, "chess_arena.db")


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
#  PGN
# ═══════════════════════════════════════════════════════════

def build_pgn(white, black, moves, result, date):
    hdr = (f'[Event "Engine Match"]\n[Site "Chess Engine Arena"]\n'
           f'[Date "{date}"]\n[Round "1"]\n[White "{white}"]\n'
           f'[Black "{black}"]\n[Result "{result}"]\n\n')
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
    """Show a promotion dialog and return chosen piece ('q','r','b','n')."""
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
#  Search Bar helper widget
# ═══════════════════════════════════════════════════════════

def make_search_bar(parent, on_search_cb, placeholder="🔍 Search…"):
    """Returns (frame, StringVar) for a live search bar."""
    frame = tk.Frame(parent, bg=PANEL_BG)
    var = tk.StringVar()

    tk.Label(frame, text="🔍", bg=PANEL_BG, fg=ACCENT,
             font=('Segoe UI', 11)).pack(side='left', padx=(8, 2))

    entry = tk.Entry(frame, textvariable=var, bg=LOG_BG, fg=TEXT,
                     insertbackground=TEXT, font=('Segoe UI', 10),
                     relief='flat', highlightthickness=1,
                     highlightcolor=ACCENT, highlightbackground='#333')
    entry.pack(side='left', fill='x', expand=True, ipady=5, padx=(0, 4))

    # Placeholder
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
#  GUI
# ═══════════════════════════════════════════════════════════

class ChessGUI:
    def __init__(self, root):
        self.root=root
        self.root.title("♟  Chess Engine Arena — Enhanced")
        self.root.configure(bg=BG)
        self.root.resizable(True,True)
        self.root.minsize(1060,780)
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

        self.board=Board()
        self.engine1=None; self.engine2=None

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

        # ── FIXED: use stable home-dir path so DB never resets ──
        self.db_path = get_db_path()
        self._init_database()

        self._build_ui()
        self._draw_board()
        self._status(f"DB: {self.db_path} | Load engines and press ▶ Start")

    def _on_closing(self):
        if self.game_running:
            self.game_running = False
            time.sleep(0.2)
        self._kill_engines()
        self.root.destroy()

    # ─── Database methods ─────────────────────────────────────────────────────

    def _init_database(self):
        """Initialize DB with WAL mode for better concurrency / no corruption."""
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

            # Apply search filter
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

            # Client-side search filter (covers all visible columns)
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

    # ─── Statistics window with search ────────────────────────────────────────

    def _show_statistics(self):
        stats_window = tk.Toplevel(self.root)
        stats_window.title("Engine Statistics")
        stats_window.configure(bg=BG)
        stats_window.geometry("720x560")

        tk.Label(stats_window, text="📊 ENGINE STATISTICS", bg=BG, fg=ACCENT,
                 font=('Segoe UI', 16, 'bold')).pack(pady=(12, 2))
        tk.Label(stats_window, text=f"📁 {self.db_path}", bg=BG, fg="#555",
                 font=('Consolas', 8), wraplength=700).pack(pady=(0, 6))

        # ── Search bar ──
        search_frame = tk.Frame(stats_window, bg=BG)
        search_frame.pack(fill='x', padx=20, pady=(0, 6))

        all_stats = [None]  # mutable container so inner func can update
        tree_ref  = [None]

        def refresh_stats(query=''):
            stats = self._get_engine_stats(search_query=query)
            all_stats[0] = stats
            tree = tree_ref[0]
            if tree is None:
                return
            for row in tree.get_children():
                tree.delete(row)
            for stat in stats:
                tree.insert('', 'end', values=(
                    stat['engine'], stat['matches'], stat['wins'],
                    stat['draws'], stat['loses'], f"{stat['win_rate']:.1f}%"))
            count_lbl.config(text=f"{len(stats)} engine(s) shown")

        sb_frame, _ = make_search_bar(search_frame, refresh_stats,
                                       placeholder="🔍 Filter engines…")
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

        tree.heading('Engine',   text='Engine')
        tree.heading('Matches',  text='Matches')
        tree.heading('Win',      text='Win')
        tree.heading('Draw',     text='Draw')
        tree.heading('Lose',     text='Lose')
        tree.heading('WinRate%', text='WinRate%')
        tree.column('Engine',   width=260)
        tree.column('Matches',  width=75, anchor='center')
        tree.column('Win',      width=55, anchor='center')
        tree.column('Draw',     width=55, anchor='center')
        tree.column('Lose',     width=55, anchor='center')
        tree.column('WinRate%', width=90, anchor='center')

        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Treeview', background=LOG_BG, foreground=TEXT,
                        fieldbackground=LOG_BG, borderwidth=0)
        style.configure('Treeview.Heading', background=BTN_BG, foreground=TEXT, borderwidth=1)
        style.map('Treeview', background=[('selected', ACCENT)])
        tree.pack(fill='both', expand=True)

        count_lbl = tk.Label(stats_window, text="", bg=BG, fg="#555",
                             font=('Segoe UI', 9))
        count_lbl.pack(pady=(0, 2))

        tip = tk.Label(stats_window,
                       text="💡 Double-click an engine row to view its game history",
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

        tk.Button(btn_frame, text="View All Game History",
                  command=lambda: self._show_game_history(),
                  bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
                  padx=15, pady=8, cursor='hand2').pack(side='left', padx=5)

        tk.Button(btn_frame, text="Refresh",
                  command=lambda: refresh_stats(''),
                  bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
                  padx=15, pady=8, cursor='hand2').pack(side='left', padx=5)

        tk.Button(btn_frame, text="Close", command=stats_window.destroy,
                  bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
                  padx=15, pady=8, cursor='hand2').pack(side='right', padx=5)

        # Initial load
        refresh_stats('')

    # ─── Game history window with search ─────────────────────────────────────

    def _show_game_history(self, filter_engine=None):
        history_window = tk.Toplevel(self.root)
        norm_filter = normalize_engine_name(filter_engine) if filter_engine else None
        history_window.title(f"Game History{' — ' + norm_filter if norm_filter else ''}")
        history_window.configure(bg=BG)
        history_window.geometry("960x640")

        # Header
        header_frame = tk.Frame(history_window, bg=BG)
        header_frame.pack(fill='x', padx=20, pady=(12, 0))
        tk.Label(header_frame, text="📜 GAME HISTORY", bg=BG, fg=ACCENT,
                 font=('Segoe UI', 16, 'bold')).pack(side='left')
        if norm_filter:
            tk.Label(header_frame, text=f"  ·  {norm_filter}", bg=BG, fg="#FFD700",
                     font=('Segoe UI', 11)).pack(side='left')
            tk.Button(header_frame, text="✕ Clear Filter",
                      command=lambda: [history_window.destroy(),
                                       self._show_game_history()],
                      bg=BTN_BG, fg=TEXT, font=('Segoe UI', 9), padx=10, pady=4,
                      cursor='hand2', relief='flat').pack(side='right')

        # ── Search bar ──
        search_container = tk.Frame(history_window, bg=BG)
        search_container.pack(fill='x', padx=20, pady=(8, 4))

        all_games_cache = [None]
        tree_ref2       = [None]
        count_lbl2      = [None]

        def refresh_history(query=''):
            games = self._get_all_games(filter_engine=filter_engine,
                                        search_query=query)
            all_games_cache[0] = games
            tree = tree_ref2[0]
            if tree is None:
                return
            for row in tree.get_children():
                tree.delete(row)
            for game in games:
                game_id, white, black, result, reason, date, time_str, moves, duration = game
                duration_str = f"{duration//60}m {duration%60}s" if duration else "N/A"
                tree.insert('', 'end', values=(
                    game_id, date, time_str, white, black,
                    result, reason, moves or 0, duration_str))
            if count_lbl2[0]:
                count_lbl2[0].config(text=f"{len(games)} game(s) shown")

        sb_frame2, _ = make_search_bar(search_container, refresh_history,
                                        placeholder="🔍 Search by engine, result, reason, date…")
        sb_frame2.pack(fill='x')

        # Tree
        tree_frame = tk.Frame(history_window, bg=BG)
        tree_frame.pack(fill='both', expand=True, padx=20, pady=(4, 0))
        scrollbar = tk.Scrollbar(tree_frame)
        scrollbar.pack(side='right', fill='y')

        columns = ('ID', 'Date', 'Time', 'White', 'Black',
                   'Result', 'Reason', 'Moves', 'Duration')
        tree = ttk.Treeview(tree_frame, columns=columns, show='headings',
                            yscrollcommand=scrollbar.set)
        scrollbar.config(command=tree.yview)
        tree_ref2[0] = tree

        for col, w in [('ID',40),('Date',80),('Time',70),('White',150),('Black',150),
                       ('Result',60),('Reason',150),('Moves',50),('Duration',80)]:
            tree.heading(col, text=col)
            anchor = 'center' if col not in ('White','Black','Reason') else 'w'
            tree.column(col, width=w, anchor=anchor)
        tree.pack(fill='both', expand=True)

        count_lbl2[0] = tk.Label(history_window, text="", bg=BG, fg="#555",
                                  font=('Segoe UI', 9))
        count_lbl2[0].pack(pady=(2, 0))

        tk.Label(history_window,
                 text="💡 Double-click a row to view PGN   |   Click White/Black cell to filter by engine",
                 bg=BG, fg="#444", font=('Segoe UI', 8)).pack(pady=(0, 4))

        def view_pgn(event=None):
            selected = tree.selection()
            if not selected:
                if event is None:
                    messagebox.showinfo("No Selection", "Please select a game.")
                return
            item = tree.item(selected[0])
            game_id = item['values'][0]
            pgn = self._get_game_pgn(game_id)
            if pgn:
                self._show_pgn_viewer(pgn, item['values'],
                                      all_games_cache[0] or [], tree)
            else:
                messagebox.showerror("Error", "Could not load PGN.")

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
                    self._show_pgn_viewer(pgn, values,
                                          all_games_cache[0] or [], tree)
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

        tk.Button(btn_frame, text="View PGN", command=view_pgn,
                  bg=ACCENT, fg=TEXT, font=('Segoe UI', 10, 'bold'),
                  padx=15, pady=8, cursor='hand2').pack(side='left', padx=5)

        if norm_filter:
            tk.Button(btn_frame, text="Show All Games",
                      command=lambda: [history_window.destroy(),
                                       self._show_game_history()],
                      bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
                      padx=15, pady=8, cursor='hand2').pack(side='left', padx=5)

        tk.Button(btn_frame, text="Refresh",
                  command=lambda: refresh_history(''),
                  bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
                  padx=15, pady=8, cursor='hand2').pack(side='left', padx=5)

        tk.Button(btn_frame, text="Close", command=history_window.destroy,
                  bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
                  padx=15, pady=8, cursor='hand2').pack(side='right', padx=5)

        # Initial load
        refresh_history('')

    # ─── PGN viewer (unchanged except minor cleanup) ──────────────────────────

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
        text_frame = tk.Frame(right_frame, bg=LOG_BG, highlightthickness=1,
                               highlightbackground='#333')
        text_frame.pack(fill='both', expand=True, pady=(0, 10))
        pgn_text = scrolledtext.ScrolledText(
            text_frame, bg=LOG_BG, fg=TEXT,
            font=('Consolas', 10), relief='flat',
            padx=10, pady=10, wrap='word')
        pgn_text.pack(fill='both', expand=True)
        pgn_text.insert('1.0', pgn)
        pgn_text.config(state='disabled')

        tk.Label(right_frame,
                 text="⌨ Move: ←→ | Start/End: Home/End | Game: PgUp/PgDn",
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
        import re
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
        self.root.columnconfigure(1,weight=1)
        self.root.rowconfigure(0,weight=1)
        lp=tk.Frame(self.root,bg=PANEL_BG,width=270)
        lp.grid(row=0,column=0,sticky='nsew',padx=(8,0),pady=8)
        lp.grid_propagate(False)
        self._build_left(lp)
        cp=tk.Frame(self.root,bg=BG)
        cp.grid(row=0,column=1,sticky='nsew',padx=8,pady=8)
        cp.rowconfigure(2,weight=0); cp.columnconfigure(0,weight=1)
        self._build_center(cp)
        rp=tk.Frame(self.root,bg=PANEL_BG,width=285)
        rp.grid(row=0,column=2,sticky='nsew',padx=(0,8),pady=8)
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
            ("▶  START GAME",     self._start_game,  True),
            ("⏸  PAUSE / RESUME", self._toggle_pause,False),
            ("⏹  STOP GAME",      self._stop_game,   False),
            ("↺  NEW GAME",       self._new_game,    False),
            ("⇅  FLIP BOARD",     self._flip_board,  False),
            ("💾  EXPORT PGN",    self._export_pgn,  False),
            ("📊  STATISTICS",    self._show_statistics, False),
        ]:
            self._btn(p,txt,cmd,accent=acc).pack(fill='x',padx=10,pady=2)
        tk.Frame(p,bg='#2a2a4a',height=1).pack(fill='x',padx=10,pady=4)
        self._lbl(p,"Material balance",8,fg="#888").pack(fill='x',padx=10)
        self.mat_lbl=tk.Label(p,text="=",bg=PANEL_BG,fg=TEXT,
                              font=('Consolas',9),anchor='center')
        self.mat_lbl.pack(fill='x',padx=10)

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
        self.status_lbl=tk.Label(p,text="",bg=BG,fg=ACCENT,
                                  font=('Segoe UI',11,'bold'),anchor='center')
        self.status_lbl.grid(row=0,column=0,sticky='ew',pady=(0,4))
        self.black_banner=tk.Label(p, textvariable=self.e1_name,
            bg="#1a1a2a", fg="#C8C8C8", font=('Segoe UI',11,'bold'),
            anchor='center', pady=6, relief='flat',
            highlightthickness=1, highlightbackground="#444444")
        self.black_banner.grid(row=1,column=0,sticky='ew',pady=(0,3))
        board_row=tk.Frame(p,bg=BG)
        board_row.grid(row=2,column=0)
        rf=tk.Frame(board_row,bg=BG); rf.pack(side='left')
        self.rank_labels=[]
        sz=self.sq_size
        for i in range(8):
            l=tk.Label(rf,text="",bg=BG,fg="#777",
                       font=('Consolas',9),width=2,anchor='e')
            l.pack(side='top',ipady=sz//2-7)
            self.rank_labels.append(l)
        bcol=tk.Frame(board_row,bg=BG); bcol.pack(side='left')
        bs=sz*8
        self.canvas=tk.Canvas(bcol,width=bs,height=bs,bg=BG,bd=0,
                               highlightthickness=2,highlightcolor=ACCENT,
                               highlightbackground='#333')
        self.canvas.pack()
        self.selected_square = None
        self.canvas.bind('<Button-1>', self._on_board_click)
        ff=tk.Frame(bcol,bg=BG); ff.pack(fill='x')
        self.file_labels=[]
        for i in range(8):
            l=tk.Label(ff,text="",bg=BG,fg="#777",
                       font=('Consolas',9),width=4,anchor='center')
            l.pack(side='left',ipadx=sz//2-8)
            self.file_labels.append(l)
        self.white_banner=tk.Label(p, textvariable=self.e2_name,
            bg="#1c2a1c", fg="#FFD700", font=('Segoe UI',11,'bold'),
            anchor='center', pady=6, relief='flat',
            highlightthickness=1, highlightbackground="#555500")
        self.white_banner.grid(row=3,column=0,sticky='ew',pady=(3,0))
        self._update_coords()
        self.check_lbl=tk.Label(p,text="",bg=BG,fg=CHECK_SQ,
                                 font=('Segoe UI',10,'bold'),anchor='center')
        self.check_lbl.grid(row=4,column=0,sticky='ew',pady=(4,0))

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

        if self.flipped:
            br, bc = 7 - row, 7 - col
        else:
            br, bc = row, col

        human_color = self.player_color.get()

        with self.board_lock:
            if (human_color == "white" and self.board.turn != 'w') or \
               (human_color == "black" and self.board.turn != 'b'):
                return

            piece_at_click = self.board.get(br, bc)
            is_own_piece = (
                piece_at_click and piece_at_click != '.' and
                ((human_color == "white" and piece_at_click.isupper()) or
                 (human_color == "black" and piece_at_click.islower()))
            )

            if self.selected_square is None:
                if is_own_piece:
                    self.selected_square = (br, bc)
                    self.root.after(0, self._draw_board)
                return

            from_r, from_c = self.selected_square

            if (br, bc) == (from_r, from_c):
                self.selected_square = None
                self.root.after(0, self._draw_board)
                return

            if is_own_piece:
                self.selected_square = (br, bc)
                self.root.after(0, self._draw_board)
                return

            to_r, to_c = br, bc
            legal_moves = self.board.legal_moves()

            matching_moves = [m for m in legal_moves
                              if m[0] == from_r and m[1] == from_c
                              and m[2] == to_r and m[3] == to_c]

            if not matching_moves:
                self.root.after(0, self._draw_board)
                return

            if any(m[4] for m in matching_moves):
                promo_piece = None
                self.selected_square = None
                self.root.after(0, self._draw_board)
                promo_piece = ask_promotion(self.root, 'w' if human_color == 'white' else 'b')
                promo_piece = promo_piece.lower()
                move_tuple = next((m for m in matching_moves if m[4] == promo_piece), None)
                if move_tuple is None:
                    move_tuple = next((m for m in matching_moves if m[4] == 'q'), matching_moves[0])
                uci = (f"{chr(ord('a')+from_c)}{8-from_r}"
                       f"{chr(ord('a')+to_c)}{8-to_r}{move_tuple[4]}")
            else:
                move_tuple = matching_moves[0]
                uci = f"{chr(ord('a')+from_c)}{8-from_r}{chr(ord('a')+to_c)}{8-to_r}"

            self.selected_square = None

            try:
                san, cap = self.board.apply_uci(uci)
            except ValueError as e:
                self.root.after(0, self._draw_board)
                messagebox.showerror("Error", f"Invalid move: {e}")
                return

            self.last_move = uci
            move_num = (len(self.board.move_history) + 1) // 2
            over, result, reason, winner_color = self.board.game_result()

        self.root.after(0, self._draw_board)
        self.root.after(0, self._update_info)

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
            self.white_banner.config(bg="#1c2a1c", highlightbackground="#555500", highlightthickness=1)
        else:
            self.white_banner.config(bg="#2a2a1a", highlightbackground=ACCENT, highlightthickness=2)
            self.black_banner.config(bg="#1a1a2a", highlightbackground="#444444", highlightthickness=1)

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
        for path,n in [(p1,1),(p2,2)]:
            if not path:
                messagebox.showerror("Error",f"Engine {n} path is empty."); return False
            if not os.path.isfile(path):
                messagebox.showerror("Error",f"Engine {n} file not found:\n{path}"); return False
            if sys.platform != 'win32' and not os.access(path, os.X_OK):
                messagebox.showerror("Error",f"Engine {n} is not executable:\n{path}"); return False
        errs=[]
        for path,name_var,n,tag in [
            (p1,self.e1_name,1,'B'),(p2,self.e2_name,2,'W')
        ]:
            try:
                self._status(f"Loading {name_var.get()}…")
                eng=UCIEngine(path,name_var.get())
                eng.start()
                if n==1: self.engine1=eng
                else:    self.engine2=eng
                self.root.after(0,self._log_eng,f"✓ {name_var.get()} ready",tag)
            except Exception as e:
                errs.append(f"Engine {n}: {e}")
        if errs:
            messagebox.showerror("Engine Error",'\n'.join(errs)); return False
        return True

    def _load_opponent_engine(self):
        path = self.e2_path.get().strip()
        if not path:
            messagebox.showerror("Error", "Engine path is empty."); return False
        if not os.path.isfile(path):
            messagebox.showerror("Error", f"Engine not found:\n{path}"); return False
        if sys.platform != 'win32' and not os.access(path, os.X_OK):
            messagebox.showerror("Error", f"Engine is not executable:\n{path}"); return False
        try:
            self._status(f"Loading {self.e2_name.get()}…")
            eng = UCIEngine(path, self.e2_name.get())
            eng.start()
            self.engine2 = eng
            self.root.after(0, self._log_eng, f"✓ {self.e2_name.get()} ready", 'W')
            return True
        except Exception as e:
            messagebox.showerror("Engine Error", str(e)); return False

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

        movetime = self.movetime.get()
        def on_info(info): self.root.after(0, lambda: self._show_eval(engine, side))

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

            self.last_move = uci
            move_num = (len(self.board.move_history) + 1) // 2
            over, result, reason, winner_color = self.board.game_result()
            in_check = self.board.in_check()

        self.root.after(0, self._draw_board)
        self.root.after(0, self._update_info)

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
        for w in (self.move_text,self.eng_log):
            w.config(state='normal'); w.delete('1.0','end'); w.config(state='disabled')
        self.board.reset(); self.last_move=None; self._pending_b=None
        self.selected_square = None
        self._engine_thinking = False
        self._draw_board(); self._update_info()
        for v in (self.e1_eval,self.e2_eval,self.e1_depth,self.e2_depth): v.set('—')
        self.mat_lbl.config(text="=")
        self.game_date=datetime.now().strftime("%Y.%m.%d")
        self.game_start_time = time.time()
        if self.play_mode.get() == "human_vs_engine":
            if not self._load_opponent_engine(): return
            self.game_running = True; self.game_paused = False; self.game_result = '*'
            if self.player_color.get() == "white":
                self.e2_name.set(f"{self.e2_name.get().split('(')[0].strip()} (Black)")
            else:
                self.e2_name.set(f"{self.e2_name.get().split('(')[0].strip()} (White)")
            if self.player_color.get() == "black":
                self._start_engine_turn()
            else:
                self._status("♔ Your turn — click a piece to move")
        else:
            if not self._load_engines(): return
            self.game_running=True; self.game_paused=False; self.game_result='*'
            self.game_thread=threading.Thread(target=self._game_loop,daemon=True)
            self.game_thread.start()

    def _toggle_pause(self):
        if not self.game_running: return
        self.game_paused=not self.game_paused
        self._status("⏸ PAUSED" if self.game_paused else "▶ Resuming…")

    def _stop_game(self):
        self.game_running=False; self.game_paused=False
        self._engine_thinking = False
        self._kill_engines(); self._status("⏹ Game stopped")

    def _new_game(self):
        self._stop_game(); time.sleep(0.15)
        self.board.reset(); self.last_move=None; self._pending_b=None
        self.selected_square = None
        self._engine_thinking = False
        self.board_lock = threading.Lock()
        for w in (self.move_text,self.eng_log):
            w.config(state='normal'); w.delete('1.0','end'); w.config(state='disabled')
        self._draw_board(); self._update_info()
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
                      self.game_date or datetime.now().strftime("%Y.%m.%d"))
        path=filedialog.asksaveasfilename(defaultextension=".pgn",
            filetypes=[("PGN","*.pgn"),("All","*.*")], title="Save PGN")
        if path:
            with open(path,'w') as f: f.write(pgn)
            messagebox.showinfo("Saved",f"PGN saved:\n{path}")

    # ─── Game over dialog ──────────────────────────────────────────────────────

    def _show_game_over_dialog(self, result, reason, winner_name):
        dialog = tk.Toplevel(self.root)
        dialog.title("Game Over")
        dialog.configure(bg=BG)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.update_idletasks()
        w = 450; h = 300
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
            tk.Label(main_frame, text=clean_name, bg=BG, fg=TEXT,
                     font=('Segoe UI', 20, 'bold')).pack(pady=5)
        tk.Frame(main_frame, bg=ACCENT, height=2).pack(fill='x', pady=15)
        tk.Label(main_frame, text=f"Result: {result}", bg=BG, fg="#AAA",
                 font=('Segoe UI', 12)).pack(pady=2)
        tk.Label(main_frame, text=reason, bg=BG, fg="#888",
                 font=('Segoe UI', 11)).pack(pady=2)
        btn_frame = tk.Frame(dialog, bg=BG)
        btn_frame.pack(fill='x', padx=20, pady=(0, 20))
        def close_dialog(): dialog.destroy()
        def new_game_and_close(): dialog.destroy(); self._new_game()
        def export_and_close(): dialog.destroy(); self._export_pgn()
        for text, cmd, accent in [
            ("New Game", new_game_and_close, True),
            ("Export PGN", export_and_close, False),
            ("Close", close_dialog, False)
        ]:
            bg_color = ACCENT if accent else BTN_BG
            btn = tk.Button(btn_frame, text=text, command=cmd, bg=bg_color, fg=TEXT,
                            activebackground=BTN_HOV, activeforeground='white',
                            relief='flat', font=('Segoe UI', 11, 'bold' if accent else 'normal'),
                            padx=20, pady=10, cursor='hand2', borderwidth=0)
            btn.pack(side='left', expand=True, fill='x', padx=5)
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
            mvs=self.board.uci_moves_str()
            def on_info(info): self.root.after(0, lambda: self._show_eval(engine, side))
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
            self.last_move=uci
            move_num=(len(self.board.move_history)+1)//2
            self.root.after(0,self._draw_board)
            self.root.after(0,self._update_info)
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
                        self.game_date or datetime.now().strftime("%Y.%m.%d"))
        self._save_game_to_db(white_name, black_name, result, reason, pgn, duration_seconds)
        if winner_name:
            msg = f"🏆 {winner_name} WINS!\n{reason}"
            status_msg = f"🏁 {normalize_engine_name(winner_name)} wins by {reason}"
        else:
            msg = f"Game ended: {result}\n{reason}"
            status_msg = f"🏁 {result} — {reason}"
        self.root.after(0, self._status, status_msg)
        self.root.after(0, self._log_result, f"{result}  —  {reason}")
        self.root.after(0, lambda: self._show_game_over_dialog(result, reason, winner_name))


# ═══════════════════════════════════════════════════════════

def main():
    root=tk.Tk()
    root.minsize(1060,780)
    try: root.iconbitmap("")
    except Exception: pass
    ChessGUI(root)
    root.mainloop()

if __name__=="__main__":
    main()