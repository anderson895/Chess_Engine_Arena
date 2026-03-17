# ═══════════════════════════════════════════════════════════
#  chess960.py — Fischer Random (Chess 960) support
# ═══════════════════════════════════════════════════════════
#
#  Provides:
#    generate_chess960_fen(sp=None)  → FEN string
#    chess960_castling_fen(back_rank) → castling field string  (e.g. "HAha")
#    show_chess960_picker(root)      → (fen, sp_number) | (None, None)
#
#  Chess960 uses "X-FEN" castling notation: uppercase letters for the
#  rook files (A–H) instead of K/Q.  Most modern UCI engines (Stockfish,
#  Komodo, etc.) accept X-FEN natively via the "UCI_Chess960" option.
# ═══════════════════════════════════════════════════════════

import random
import tkinter as tk
from tkinter import ttk

from constants import BG, PANEL_BG, ACCENT, TEXT, BTN_BG, BTN_HOV, LOG_BG, UNICODE


# ── Position generator ────────────────────────────────────

def generate_chess960_fen(sp: int | None = None) -> tuple[str, int]:
    """
    Generate a Chess960 starting position.

    Parameters
    ----------
    sp : int | None
        Starting-position number 0-959.  If None, a random one is chosen.

    Returns
    -------
    (fen: str, sp_number: int)
    """
    if sp is None:
        sp = random.randint(0, 959)
    sp = max(0, min(959, sp))

    back = _sp_to_back_rank(sp)
    castling = _castling_field(back)

    # Build FEN rows
    white_back = ''.join(back).upper()
    white_pawns = 'PPPPPPPP'
    black_pawns = 'pppppppp'
    black_back  = ''.join(back).lower()

    fen = (
        f"{black_back}/{black_pawns}/8/8/8/8/{white_pawns}/{white_back} "
        f"w {castling} - 0 1"
    )
    return fen, sp


def _sp_to_back_rank(sp: int) -> list[str]:
    """
    Convert a Chess960 starting-position number (0-959) to the back-rank
    piece list [col0..col7], lowercase.

    Uses the standard Reinfeld / FIDE numbering algorithm.
    """
    pieces = [None] * 8

    # 1. Light-square bishop: positions 1,3,5,7
    n, sp = divmod(sp, 4)
    pieces[sp * 2 + 1] = 'b'

    # 2. Dark-square bishop: positions 0,2,4,6
    n, r = divmod(n, 4)
    pieces[r * 2] = 'b'

    # 3. Queen in the remaining 6 squares
    n, r = divmod(n, 6)
    empties = [i for i in range(8) if pieces[i] is None]
    pieces[empties[r]] = 'q'

    # 4. Knights: use table for the remaining 5 squares (10 combinations)
    KNIGHT_TABLE = [
        (0, 1), (0, 2), (0, 3), (0, 4),
        (1, 2), (1, 3), (1, 4),
        (2, 3), (2, 4),
        (3, 4),
    ]
    kn1, kn2 = KNIGHT_TABLE[n]
    empties = [i for i in range(8) if pieces[i] is None]
    pieces[empties[kn1]] = 'n'
    pieces[empties[kn2]] = 'n'

    # 5. Fill remaining three squares with R K R (rook, king, rook)
    empties = [i for i in range(8) if pieces[i] is None]
    pieces[empties[0]] = 'r'
    pieces[empties[1]] = 'k'
    pieces[empties[2]] = 'r'

    return pieces


def _castling_field(back: list[str]) -> str:
    """
    Return X-FEN castling string for the given back rank.
    White castling rights use uppercase file letters (A-H),
    black use lowercase.
    """
    king_col  = back.index('k')
    rook_cols = [i for i, p in enumerate(back) if p == 'r']

    # Kingside rook = the rook to the RIGHT of the king
    ks_col = next((c for c in rook_cols if c > king_col), None)
    # Queenside rook = the rook to the LEFT of the king
    qs_col = next((c for c in reversed(rook_cols) if c < king_col), None)

    field = ''
    if ks_col is not None:
        field += chr(ord('A') + ks_col)   # e.g. 'H' for standard
    if qs_col is not None:
        field += chr(ord('A') + qs_col)   # e.g. 'A' for standard
    # Black mirrors white
    field += field.lower()
    return field if field else '-'


# ── Picker dialog ─────────────────────────────────────────

def show_chess960_picker(root) -> tuple[str | None, int | None]:
    """
    Modal dialog for picking a Chess960 starting position.

    Returns
    -------
    (fen: str, sp_number: int) if confirmed, or (None, None) if cancelled.
    """
    result_fen = [None]
    result_sp  = [None]

    dialog = tk.Toplevel(root)
    dialog.title("♟  Fischer Random — Chess 960")
    dialog.configure(bg=BG)
    dialog.resizable(False, False)
    dialog.transient(root)
    dialog.grab_set()

    sw, sh = dialog.winfo_screenwidth(), dialog.winfo_screenheight()
    w, h = 560, 480
    dialog.geometry(f'{w}x{h}+{(sw-w)//2}+{(sh-h)//2}')

    # ── Header ────────────────────────────────────────────
    tk.Label(dialog, text="♟  FISCHER RANDOM  ·  Chess 960",
             bg=BG, fg=ACCENT, font=('Segoe UI', 15, 'bold')).pack(pady=(16, 2))
    tk.Label(dialog, text="960 starting positions — king always between the two rooks",
             bg=BG, fg="#666", font=('Segoe UI', 9)).pack(pady=(0, 4))
    tk.Frame(dialog, bg=ACCENT, height=2).pack(fill='x', padx=20, pady=(4, 12))

    # ── SP number entry ───────────────────────────────────
    sp_frame = tk.Frame(dialog, bg=BG)
    sp_frame.pack(padx=24, fill='x')

    tk.Label(sp_frame, text="SP #  (0 – 959):", bg=BG, fg=TEXT,
             font=('Segoe UI', 10, 'bold')).pack(side='left')

    sp_var = tk.StringVar(value=str(random.randint(0, 959)))
    sp_entry = tk.Entry(sp_frame, textvariable=sp_var, width=6,
                        bg=LOG_BG, fg=TEXT, insertbackground=TEXT,
                        font=('Consolas', 12, 'bold'), relief='flat',
                        highlightthickness=1, highlightcolor=ACCENT,
                        highlightbackground='#333', justify='center')
    sp_entry.pack(side='left', padx=(10, 6), ipady=4)

    tk.Button(sp_frame, text="🎲  Random SP",
              command=lambda: [sp_var.set(str(random.randint(0, 959))), _refresh()],
              bg=BTN_BG, fg=TEXT, relief='flat', font=('Segoe UI', 9),
              padx=10, pady=4, cursor='hand2').pack(side='left', padx=4)

    sp_var.trace_add('write', lambda *_: _refresh())

    # ── Board preview ─────────────────────────────────────
    preview_frame = tk.Frame(dialog, bg=BG)
    preview_frame.pack(pady=(14, 4))

    SQ = 52
    canvas = tk.Canvas(preview_frame, width=SQ * 8, height=SQ,
                       bg=BG, bd=0, highlightthickness=2,
                       highlightcolor=ACCENT, highlightbackground='#333')
    canvas.pack()

    # ── Info labels ───────────────────────────────────────
    info_frame = tk.Frame(dialog, bg=PANEL_BG)
    info_frame.pack(fill='x', padx=20, pady=(8, 4))

    sp_label    = tk.Label(info_frame, text="", bg=PANEL_BG, fg=ACCENT,
                           font=('Segoe UI', 11, 'bold'))
    sp_label.pack(pady=(6, 2))

    fen_var = tk.StringVar()
    tk.Label(info_frame, textvariable=fen_var, bg=PANEL_BG, fg="#AAA",
             font=('Consolas', 8), wraplength=500).pack(pady=(0, 6))

    castling_label = tk.Label(info_frame, text="", bg=PANEL_BG, fg="#00BFFF",
                              font=('Segoe UI', 9))
    castling_label.pack(pady=(0, 6))

    # ── Standard position shortcut ────────────────────────
    std_frame = tk.Frame(dialog, bg=BG)
    std_frame.pack(pady=(4, 0))
    tk.Label(std_frame, text="Quick pick:", bg=BG, fg="#888",
             font=('Segoe UI', 9)).pack(side='left', padx=(0, 8))
    for label, sp_num in [("SP 518 (Standard)", 518),
                           ("SP 0", 0), ("SP 959", 959)]:
        tk.Button(std_frame, text=label,
                  command=lambda n=sp_num: [sp_var.set(str(n)), _refresh()],
                  bg=BTN_BG, fg=TEXT, relief='flat',
                  font=('Segoe UI', 8), padx=8, pady=3,
                  cursor='hand2').pack(side='left', padx=3)

    # ── State ─────────────────────────────────────────────
    current = {'fen': None, 'sp': None, 'back': None}

    def _refresh():
        try:
            sp_num = int(sp_var.get().strip())
            if not (0 <= sp_num <= 959):
                raise ValueError
        except ValueError:
            canvas.delete('all')
            sp_label.config(text="Enter a number 0 – 959")
            fen_var.set("")
            castling_label.config(text="")
            current['fen'] = None
            return

        fen, sp_num = generate_chess960_fen(sp_num)
        back = _sp_to_back_rank(sp_num)
        current['fen']  = fen
        current['sp']   = sp_num
        current['back'] = back

        # Update labels
        sp_label.config(text=f"Starting Position #{sp_num}")
        fen_var.set(fen)
        castling_parts = fen.split()[2]
        castling_label.config(
            text=f"Castling rights: {castling_parts}  "
                 f"({'X-FEN / Chess960 notation' if castling_parts not in ('KQkq','-') else 'Standard notation'})")

        # Draw preview back rank
        _draw_preview(back)

    def _draw_preview(back):
        canvas.delete('all')
        LIGHT = "#F0D9B5"; DARK = "#B58863"
        for col, piece in enumerate(back):
            color = LIGHT if col % 2 == 0 else DARK
            x1, y1 = col * SQ, 0
            x2, y2 = x1 + SQ, SQ
            canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline='')
            sym = UNICODE.get(piece.upper(), piece.upper())
            # White piece on the back rank
            canvas.create_text(x1 + SQ//2 + 1, y1 + SQ//2 + 2,
                                text=sym, font=('Segoe UI', int(SQ * 0.52)),
                                fill='#000000')
            canvas.create_text(x1 + SQ//2, y1 + SQ//2,
                                text=sym, font=('Segoe UI', int(SQ * 0.52)),
                                fill='#F5F5F5')
            # File label
            canvas.create_text(x1 + SQ - 6, y2 - 6,
                                text=chr(ord('a') + col),
                                font=('Consolas', 7),
                                fill=DARK if color == LIGHT else LIGHT)
        canvas.create_rectangle(0, 0, SQ * 8 - 1, SQ - 1, outline='#555', width=1)

    # ── Footer ────────────────────────────────────────────
    foot = tk.Frame(dialog, bg=BG)
    foot.pack(side='bottom', fill='x', padx=20, pady=16)

    def _confirm():
        if current['fen'] is None:
            return
        result_fen[0] = current['fen']
        result_sp[0]  = current['sp']
        dialog.destroy()

    def _cancel():
        dialog.destroy()

    tk.Button(foot, text="✔  Play this Position", command=_confirm,
              bg=ACCENT, fg='white', activebackground=BTN_HOV,
              relief='flat', font=('Segoe UI', 11, 'bold'),
              padx=16, pady=10, cursor='hand2').pack(side='left', expand=True, fill='x', padx=(0, 8))

    tk.Button(foot, text="✕  Cancel", command=_cancel,
              bg=BTN_BG, fg=TEXT, activebackground=BTN_HOV,
              relief='flat', font=('Segoe UI', 11),
              padx=16, pady=10, cursor='hand2').pack(side='left', expand=True, fill='x')

    dialog.bind('<Return>', lambda e: _confirm())
    dialog.bind('<Escape>', lambda e: _cancel())

    _refresh()
    root.wait_window(dialog)
    return result_fen[0], result_sp[0]
