# ═══════════════════════════════════════════════════════════
#  dialogs.py — Reusable Tkinter dialog windows
# ═══════════════════════════════════════════════════════════

import tkinter as tk
from tkinter import ttk, messagebox
from core.constants import (
    BG, PANEL_BG, ACCENT, TEXT, BTN_BG, BTN_HOV, LOG_BG,
)
from core.utils import normalize_engine_name


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


# ═══════════════════════════════════════════════════════════
#  Opening selection dialog
# ═══════════════════════════════════════════════════════════

def ask_opening_choice(root, opening_book):
    """
    Show a modal dialog for picking a starting opening position.

    Parameters
    ----------
    root         : tk.Tk | tk.Toplevel
    opening_book : OpeningBook instance (must be loaded)

    Returns
    -------
    (uci_moves: list[str], opening_name: str) | (None, None) if cancelled / random start
    The caller should apply the returned uci_moves to the board before starting the game.
    """
    result_moves = [None]
    result_name  = [None]

    dialog = tk.Toplevel(root)
    dialog.title("📖  Choose Starting Opening")
    dialog.configure(bg=BG)
    dialog.resizable(True, True)
    dialog.transient(root)
    dialog.grab_set()

    sw, sh = dialog.winfo_screenwidth(), dialog.winfo_screenheight()
    w, h = min(780, sw - 60), min(620, sh - 80)
    dialog.geometry(f'{w}x{h}+{(sw-w)//2}+{(sh-h)//2}')
    dialog.minsize(640, 480)

    # ── Build full entry list from opening book ────────────
    all_entries = []
    seen = set()
    for seq, eco, name in opening_book._entries:
        key = (eco, name)
        if key not in seen:
            seen.add(key)
            all_entries.append((eco, name, list(seq)))
    # Sort alphabetically by name for easier browsing
    all_entries.sort(key=lambda x: x[1])

    # ── Header ────────────────────────────────────────────
    hdr = tk.Frame(dialog, bg=BG)
    hdr.pack(fill='x', padx=20, pady=(16, 0))
    tk.Label(hdr, text="📖  CHOOSE STARTING OPENING", bg=BG, fg=ACCENT,
             font=('Segoe UI', 15, 'bold')).pack(anchor='w')
    tk.Label(hdr, text=f"{len(all_entries)} openings available — engines will start from this position",
             bg=BG, fg="#666", font=('Segoe UI', 9)).pack(anchor='w', pady=(2, 0))
    tk.Frame(dialog, bg=ACCENT, height=2).pack(fill='x', padx=20, pady=(8, 6))

    # ── ECO filter buttons ────────────────────────────────
    eco_bar = tk.Frame(dialog, bg=PANEL_BG)
    eco_bar.pack(fill='x', padx=20, pady=(0, 4))
    tk.Label(eco_bar, text="ECO:", bg=PANEL_BG, fg="#AAA",
             font=('Segoe UI', 8, 'bold')).pack(side='left', padx=(6, 4))

    active_eco_filter = [None]  # None = show all

    eco_btns = {}

    def apply_eco_filter(letter):
        active_eco_filter[0] = letter
        for l, b in eco_btns.items():
            b.config(bg=ACCENT if l == letter else BTN_BG)
        _filter(search_var.get() if 'search_var' in dir() else '')

    for letter in ['All', 'A', 'B', 'C', 'D', 'E']:
        lbl = letter
        btn = tk.Button(
            eco_bar, text=lbl,
            command=lambda l=letter: apply_eco_filter(None if l == 'All' else l),
            bg=ACCENT if letter == 'All' else BTN_BG,
            fg=TEXT, relief='flat', font=('Segoe UI', 8, 'bold'),
            padx=10, pady=3, cursor='hand2')
        btn.pack(side='left', padx=2, pady=4)
        eco_btns[letter] = btn

    # ── Search bar ────────────────────────────────────────
    search_frame = tk.Frame(dialog, bg=BG)
    search_frame.pack(fill='x', padx=20, pady=(0, 4))

    search_var = tk.StringVar()
    tk.Label(search_frame, text="🔍", bg=BG, fg=ACCENT,
             font=('Segoe UI', 11)).pack(side='left', padx=(0, 4))
    search_entry = tk.Entry(search_frame, textvariable=search_var,
                            bg=LOG_BG, fg=TEXT, insertbackground=TEXT,
                            font=('Segoe UI', 10), relief='flat',
                            highlightthickness=1, highlightcolor=ACCENT,
                            highlightbackground='#333')
    search_entry.pack(side='left', fill='x', expand=True, ipady=5)
    tk.Button(search_frame, text='✕',
              command=lambda: search_var.set(''),
              bg=BG, fg='#666', relief='flat', font=('Segoe UI', 9),
              cursor='hand2', padx=4).pack(side='left', padx=(4, 0))

    # ── Treeview ──────────────────────────────────────────
    tree_frame = tk.Frame(dialog, bg=BG)
    tree_frame.pack(fill='both', expand=True, padx=20, pady=(0, 4))

    scrollbar = tk.Scrollbar(tree_frame)
    scrollbar.pack(side='right', fill='y')

    style = ttk.Style()
    style.theme_use('clam')
    style.configure('OpenDlg.Treeview',
                    background=LOG_BG, foreground=TEXT,
                    fieldbackground=LOG_BG, borderwidth=0, rowheight=26)
    style.configure('OpenDlg.Treeview.Heading',
                    background=BTN_BG, foreground=TEXT,
                    borderwidth=1, font=('Segoe UI', 9, 'bold'))
    style.map('OpenDlg.Treeview',
              background=[('selected', ACCENT)])

    columns = ('ECO', 'Name', 'Moves')
    tree = ttk.Treeview(tree_frame, columns=columns, show='headings',
                        style='OpenDlg.Treeview',
                        yscrollcommand=scrollbar.set, selectmode='browse')
    scrollbar.config(command=tree.yview)

    for col, w, anch in [('ECO', 70, 'center'), ('Name', 360, 'w'), ('Moves', 260, 'w')]:
        tree.column(col, width=w, anchor=anch)
        tree.heading(col, text=col)
    tree.pack(fill='both', expand=True)

    count_lbl = tk.Label(dialog, text="", bg=BG, fg="#555", font=('Segoe UI', 9))
    count_lbl.pack(pady=(0, 2))

    # ── Preview label ─────────────────────────────────────
    preview_var = tk.StringVar(value="Select an opening to preview its moves")
    preview_lbl = tk.Label(dialog, textvariable=preview_var,
                           bg=PANEL_BG, fg="#00BFFF",
                           font=('Segoe UI', 9, 'italic'),
                           anchor='w', padx=10, pady=6, wraplength=w - 60)
    preview_lbl.pack(fill='x', padx=20, pady=(0, 4))

    # ── Data population ───────────────────────────────────
    visible_entries = [list(all_entries)]  # mutable ref

    def _populate(entries):
        for item in tree.get_children():
            tree.delete(item)
        for eco, name, uci_seq in entries:
            moves_preview = ' '.join(uci_seq[:6])
            if len(uci_seq) > 6:
                moves_preview += '…'
            tree.insert('', 'end', values=(eco, name, moves_preview))
        visible_entries[0] = entries
        count_lbl.config(text=f"{len(entries)} openings shown")

    def _filter(query=''):
        q = query.strip().lower()
        eco_f = active_eco_filter[0]
        filtered = []
        for eco, name, seq in all_entries:
            if eco_f and not eco.startswith(eco_f):
                continue
            if q and q not in name.lower() and q not in eco.lower():
                continue
            filtered.append((eco, name, seq))
        _populate(filtered)

    search_var.trace_add('write', lambda *_: _filter(search_var.get()))

    def on_select(event=None):
        sel = tree.selection()
        if not sel:
            return
        vals = tree.item(sel[0])['values']
        eco, name = vals[0], vals[1]
        # Find full UCI sequence
        for e, n, seq in visible_entries[0]:
            if e == eco and n == name:
                moves_str = ' '.join(seq)
                preview_var.set(f"📖 {eco} · {name}  →  {moves_str}")
                break

    tree.bind('<<TreeviewSelect>>', on_select)

    def _confirm():
        sel = tree.selection()
        if not sel:
            messagebox.showwarning("No Selection",
                                   "Please select an opening first.",
                                   parent=dialog)
            return
        vals = tree.item(sel[0])['values']
        eco, name = vals[0], vals[1]
        for e, n, seq in visible_entries[0]:
            if e == eco and n == name:
                result_moves[0] = seq
                result_name[0]  = f"{eco} · {name}" if eco else name
                break
        dialog.destroy()

    def _random():
        import random
        entry = random.choice(all_entries)
        result_moves[0] = entry[2]
        result_name[0]  = f"{entry[0]} · {entry[1]}" if entry[0] else entry[1]
        dialog.destroy()

    def _no_opening():
        result_moves[0] = []
        result_name[0]  = None
        dialog.destroy()

    # ── Footer ────────────────────────────────────────────
    foot = tk.Frame(dialog, bg=BG)
    foot.pack(fill='x', padx=20, pady=(0, 16))

    tk.Button(foot, text="✔  Start with this Opening",
              command=_confirm,
              bg=ACCENT, fg='white', activebackground=BTN_HOV,
              relief='flat', font=('Segoe UI', 11, 'bold'),
              padx=14, pady=10, cursor='hand2').pack(side='left', expand=True, fill='x', padx=(0, 6))

    tk.Button(foot, text="🎲  Random",
              command=_random,
              bg=BTN_BG, fg=TEXT, activebackground=BTN_HOV,
              relief='flat', font=('Segoe UI', 10),
              padx=14, pady=10, cursor='hand2').pack(side='left', padx=(0, 6))

    tk.Button(foot, text="♟  Normal Start",
              command=_no_opening,
              bg=BTN_BG, fg=TEXT, activebackground=BTN_HOV,
              relief='flat', font=('Segoe UI', 10),
              padx=14, pady=10, cursor='hand2').pack(side='left', padx=(0, 6))

    tk.Button(foot, text="✕  Cancel",
              command=dialog.destroy,
              bg=BTN_BG, fg='#888', activebackground=BTN_HOV,
              relief='flat', font=('Segoe UI', 10),
              padx=14, pady=10, cursor='hand2').pack(side='left')

    tree.bind('<Double-1>', lambda e: _confirm())
    dialog.bind('<Escape>', lambda e: dialog.destroy())
    dialog.bind('<Return>', lambda e: _confirm())

    _populate(all_entries)
    search_entry.focus_set()

    root.wait_window(dialog)
    return result_moves[0], result_name[0]