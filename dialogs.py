# ═══════════════════════════════════════════════════════════
#  dialogs.py — Reusable Tkinter dialog windows
# ═══════════════════════════════════════════════════════════

import tkinter as tk
from tkinter import ttk, messagebox
from constants import (
    BG, PANEL_BG, ACCENT, TEXT, BTN_BG, BTN_HOV, LOG_BG,
)
from utils import normalize_engine_name


# ═══════════════════════════════════════════════════════════
#  Promotion dialog
# ═══════════════════════════════════════════════════════════

def ask_promotion(root, color):
    """
    Show a modal dialog asking the player which piece to promote to.

    Parameters
    ----------
    root  : tk.Tk | tk.Toplevel  — parent window
    color : str                  — 'w' for White, 'b' for Black

    Returns
    -------
    str — one of 'q', 'r', 'b', 'n'
    """
    result = [None]
    dialog = tk.Toplevel(root)
    dialog.title("Promote Pawn")
    dialog.configure(bg=BG)
    dialog.resizable(False, False)
    dialog.transient(root)
    dialog.grab_set()

    w, h = 340, 140
    x = (dialog.winfo_screenwidth()  // 2) - (w // 2)
    y = (dialog.winfo_screenheight() // 2) - (h // 2)
    dialog.geometry(f'{w}x{h}+{x}+{y}')

    tk.Label(dialog, text="Choose promotion piece:", bg=BG, fg=TEXT,
             font=('Segoe UI', 12, 'bold')).pack(pady=(15, 10))

    btn_frame = tk.Frame(dialog, bg=BG)
    btn_frame.pack()

    pieces = [
        ('q', '♕' if color == 'w' else '♛', 'Queen'),
        ('r', '♖' if color == 'w' else '♜', 'Rook'),
        ('b', '♗' if color == 'w' else '♝', 'Bishop'),
        ('n', '♘' if color == 'w' else '♞', 'Knight'),
    ]

    def choose(p):
        result[0] = p
        dialog.destroy()

    for piece_char, symbol, name in pieces:
        f = tk.Frame(btn_frame, bg=BG)
        f.pack(side='left', padx=8)
        btn = tk.Button(
            f, text=symbol,
            command=lambda p=piece_char: choose(p),
            bg=BTN_BG,
            fg='#FFD700' if color == 'w' else '#CCCCCC',
            font=('Segoe UI', 24), width=2, relief='flat',
            cursor='hand2', activebackground=ACCENT)
        btn.pack()
        tk.Label(f, text=name, bg=BG, fg="#888", font=('Segoe UI', 8)).pack()

    dialog.protocol("WM_DELETE_WINDOW", lambda: choose('q'))
    root.wait_window(dialog)
    return result[0] or 'q'


# ═══════════════════════════════════════════════════════════
#  Stop-game / result-entry dialog
# ═══════════════════════════════════════════════════════════

def ask_stop_result(root, white_name, black_name):
    """
    Show a modal dialog letting the user pick a result before stopping.

    Returns
    -------
    (result: str | None, reason: str | None)
        result is one of "1-0", "0-1", "1/2-1/2", "*", or None if cancelled.
    """
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
    h  = max(min(500, sh - 100), 480)
    x  = (sw - w) // 2
    y  = (sh - h) // 2
    dialog.geometry(f'{w}x{h}+{x}+{y}')
    dialog.minsize(480, 420)

    chosen_result = tk.StringVar(value="")
    chosen_reason = tk.StringVar(value="")

    # ── Header ────────────────────────────────────────────
    hdr = tk.Frame(dialog, bg=BG)
    hdr.pack(fill='x', padx=24, pady=(20, 0))
    tk.Label(hdr, text="⏹  STOP GAME", bg=BG, fg=ACCENT,
             font=('Segoe UI', 17, 'bold')).pack(anchor='w')
    tk.Frame(dialog, bg=ACCENT, height=2).pack(fill='x', padx=24, pady=(8, 12))
    tk.Label(dialog, text="Select the result to record before stopping:",
             bg=BG, fg=TEXT, font=('Segoe UI', 11)).pack(anchor='w', padx=24, pady=(0, 10))

    # ── Result buttons ────────────────────────────────────
    btn_area = tk.Frame(dialog, bg=BG)
    btn_area.pack(fill='x', padx=24)

    RESULTS = [
        ("1-0",     f"⬜  {normalize_engine_name(white_name)} wins  (White)", "#FFD700"),
        ("0-1",     f"⬛  {normalize_engine_name(black_name)} wins  (Black)", "#C8C8C8"),
        ("1/2-1/2", "½ - ½   Draw",                                           "#00BFFF"),
        ("*",       "✕   No result / Abort",                                  "#777777"),
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

    REASON_OPTIONS = {
        "1-0":     ["White wins", "White wins on time", "Black resigned",
                    "Black forfeits", "Illegal move by Black"],
        "0-1":     ["Black wins", "Black wins on time", "White resigned",
                    "White forfeits", "Illegal move by White"],
        "1/2-1/2": ["Draw by agreement", "Stalemate", "Draw by repetition",
                    "Draw by 50-move rule", "Draw by insufficient material"],
        "*":       ["Game aborted", "No result", "Stopped by user"],
    }

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

    # ── Reason dropdown ───────────────────────────────────
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

    # ── Footer buttons ────────────────────────────────────
    foot = tk.Frame(dialog, bg=BG)
    foot.pack(side='bottom', fill='x', padx=24, pady=18)

    def _confirm():
        r = chosen_result.get()
        if not r:
            messagebox.showwarning("No Result", "Please select a result first.",
                                   parent=dialog)
            return
        result_val[0] = r
        reason_val[0] = chosen_reason.get().strip() or "Stopped by user"
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
#  Search bar widget
# ═══════════════════════════════════════════════════════════

def make_search_bar(parent, on_search_cb, placeholder="🔍 Search…"):
    """
    Create a search-bar widget with placeholder text and a clear button.

    Parameters
    ----------
    parent       : tk widget
    on_search_cb : callable(str)  — called with the current query on each change
    placeholder  : str

    Returns
    -------
    (frame, StringVar)
    """
    frame = tk.Frame(parent, bg=PANEL_BG)
    var   = tk.StringVar()

    tk.Label(frame, text="🔍", bg=PANEL_BG, fg=ACCENT,
             font=('Segoe UI', 11)).pack(side='left', padx=(8, 2))

    entry = tk.Entry(frame, textvariable=var, bg=LOG_BG, fg=TEXT,
                     insertbackground=TEXT, font=('Segoe UI', 10),
                     relief='flat', highlightthickness=1,
                     highlightcolor=ACCENT, highlightbackground='#333')
    entry.pack(side='left', fill='x', expand=True, ipady=5, padx=(0, 4))

    # Placeholder behaviour
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

    entry.bind('<FocusIn>',  on_focus_in)
    entry.bind('<FocusOut>', on_focus_out)

    def clear_search():
        entry.delete(0, 'end')
        entry.insert(0, placeholder)
        entry.config(fg='#666')
        on_search_cb('')

    clear_btn = tk.Button(
        frame, text='✕', command=clear_search,
        bg=PANEL_BG, fg='#666', relief='flat',
        font=('Segoe UI', 9), cursor='hand2',
        activebackground=PANEL_BG, activeforeground=ACCENT, padx=4)
    clear_btn.pack(side='left', padx=(0, 4))

    def _on_var_change(*_):
        val = var.get()
        on_search_cb('' if val == placeholder else val)

    var.trace_add('write', _on_var_change)
    return frame, var
