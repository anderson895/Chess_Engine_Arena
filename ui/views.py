# ═══════════════════════════════════════════════════════════
#  views.py — Statistics, Rankings, Game History, PGN viewer
# ═══════════════════════════════════════════════════════════

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from core.constants import (
    BG, PANEL_BG, ACCENT, TEXT, BTN_BG, BTN_HOV,
    LOG_BG, RANK_TIERS, QUALITY_COLORS,
)
from core.utils import normalize_engine_name, get_tier
from core.elo import compute_elo_ratings, compute_elo_history
from core.board import Board
from ui.dialogs import make_search_bar


# ─── Shared ttk styling ───────────────────────────────────

def _apply_tree_style():
    style = ttk.Style()
    style.theme_use('clam')
    style.configure('Treeview', background=LOG_BG, foreground=TEXT,
                    fieldbackground=LOG_BG, borderwidth=0, rowheight=28)
    style.configure('Treeview.Heading', background=BTN_BG, foreground=TEXT,
                    borderwidth=1, font=('Segoe UI', 9, 'bold'))
    style.map('Treeview', background=[('selected', ACCENT)])
    style.map('Treeview.Heading', background=[('active', ACCENT)])


def _unpack_game_row(game):
    """
    Safely unpack a game row returned by Database.get_all_games().

    Supports both the legacy 9-column schema and the new 10-column schema
    that includes a 'source' column at the end.

    Returns
    -------
    tuple: (game_id, white, black, result, reason, date, time_str,
            moves, duration, source)
    """
    if len(game) >= 10:
        game_id, white, black, result, reason, date, time_str, moves, duration, source = game[:10]
    else:
        game_id, white, black, result, reason, date, time_str, moves, duration = game[:9]
        source = 'regular'
    return game_id, white, black, result, reason, date, time_str, moves, duration, source


# ═══════════════════════════════════════════════════════════
#  Rankings window
# ═══════════════════════════════════════════════════════════

def show_rankings(root, db):
    """
    Open the Engine Rankings leaderboard.

    Parameters
    ----------
    root : tk.Tk | tk.Toplevel
    db   : database.Database  instance
    """
    win = tk.Toplevel(root)
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
    legend = tk.Frame(win, bg=PANEL_BG)
    legend.pack(fill='x', padx=20, pady=(0, 8))
    tk.Label(legend, text="  Tiers: ", bg=PANEL_BG, fg="#AAA",
             font=('Segoe UI', 8)).pack(side='left')
    for threshold, label, color in RANK_TIERS:
        tk.Label(legend,
                 text=f"  {label} ≥{threshold}" if threshold > 0 else f"  {label}",
                 bg=PANEL_BG, fg=color, font=('Segoe UI', 8)).pack(side='left')

    # ── Data refs ─────────────────────────────────────────
    all_data_ref = [None]
    tree_ref     = [None]
    count_lbl    = [None]

    def refresh(query=''):
        games_raw   = db.get_all_games_for_elo()
        elo_ratings = compute_elo_ratings(games_raw)
        stats_list  = db.get_engine_stats()
        stats_map   = {s['engine']: s for s in stats_list}

        rows = []
        for engine, elo in elo_ratings.items():
            s = stats_map.get(engine, {})
            tier_lbl, tier_col = get_tier(elo)
            rows.append({
                'engine':   engine,
                'elo':      elo,
                'tier':     tier_lbl,
                'tier_col': tier_col,
                'matches':  s.get('matches',  0),
                'wins':     s.get('wins',     0),
                'draws':    s.get('draws',    0),
                'loses':    s.get('loses',    0),
                'win_rate': s.get('win_rate', 0.0),
            })

        rows.sort(key=lambda x: x['elo'], reverse=True)
        for i, row in enumerate(rows, 1):
            row['rank'] = i
        total = len(rows)

        if query:
            q = query.lower()
            rows = [r for r in rows if q in r['engine'].lower() or q in r['tier'].lower()]

        all_data_ref[0] = rows
        _render(rows, total)

    def _render(rows, total=None):
        tree = tree_ref[0]
        if not tree: return
        for item in tree.get_children():
            tree.delete(item)
        for row in rows:
            tree.insert('', 'end', values=(
                f"#{row['rank']}", row['engine'], row['elo'], row['tier'],
                row['matches'], row['wins'], row['draws'], row['loses'],
                f"{row['win_rate']:.1f}%",
            ), tags=(row['tier_col'],))
        if count_lbl[0]:
            shown = len(rows)
            if total is not None and shown != total:
                count_lbl[0].config(text=f"Showing {shown} of {total} engine(s)")
            else:
                count_lbl[0].config(text=f"{shown} engine(s) ranked")

    # ── Search bar ────────────────────────────────────────
    sb_container = tk.Frame(win, bg=BG)
    sb_container.pack(fill='x', padx=20, pady=(0, 6))
    sb_frame, _ = make_search_bar(sb_container, refresh,
                                   placeholder="🔍 Filter engines or tiers…")
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
    _apply_tree_style()

    for col, w, anch in [
        ('Rank',   55, 'center'), ('Engine', 230, 'w'),
        ('Elo',    70, 'center'), ('Tier',  140, 'w'),
        ('Games',  55, 'center'), ('W',      45, 'center'),
        ('D',      45, 'center'), ('L',      45, 'center'),
        ('WR%',    65, 'center'),
    ]:
        tree.column(col, width=w, anchor=anch)
        tree.heading(col, text=col)

    for _, label, color in RANK_TIERS:
        tree.tag_configure(color, foreground=color)

    tree.pack(fill='both', expand=True)

    count_lbl[0] = tk.Label(win, text="", bg=BG, fg="#555", font=('Segoe UI', 9))
    count_lbl[0].pack(pady=(2, 0))
    tk.Label(win, text="💡 Double-click a row to see Elo history  ·  Elo starts at 1500, K=32",
             bg=BG, fg="#444", font=('Segoe UI', 8)).pack(pady=(0, 4))

    def on_double_click(event):
        sel = tree.selection()
        if not sel: return
        engine_name = tree.item(sel[0])['values'][1]
        show_elo_history(root, db, engine_name)

    tree.bind('<Double-1>', on_double_click)

    # ── Footer ────────────────────────────────────────────
    btn_frame = tk.Frame(win, bg=BG)
    btn_frame.pack(fill='x', padx=20, pady=(0, 14))
    tk.Button(btn_frame, text="🔄 Refresh", command=lambda: refresh(''),
              bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
              padx=15, pady=8, cursor='hand2', relief='flat').pack(side='left', padx=5)
    tk.Button(btn_frame, text="📊 Statistics",
              command=lambda: show_statistics(root, db),
              bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
              padx=15, pady=8, cursor='hand2', relief='flat').pack(side='left', padx=5)
    tk.Button(btn_frame, text="✕ Close", command=win.destroy,
              bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
              padx=15, pady=8, cursor='hand2', relief='flat').pack(side='right', padx=5)
    refresh('')


# ═══════════════════════════════════════════════════════════
#  Elo history chart window
# ═══════════════════════════════════════════════════════════

def show_elo_history(root, db, engine_name):
    """Draw a canvas Elo-history chart for one engine."""
    games_raw = db.get_all_games_for_elo()
    history   = compute_elo_history(games_raw, engine_name)

    if not history:
        messagebox.showinfo("No Data", f"No games found for:\n{engine_name}")
        return

    win = tk.Toplevel(root)
    win.title(f"📈 Elo History — {engine_name}")
    win.configure(bg=BG)
    win.geometry("700x500")
    win.resizable(True, True)

    tk.Label(win, text=f"📈 Elo History: {engine_name}",
             bg=BG, fg=ACCENT, font=('Segoe UI', 14, 'bold')).pack(pady=(14, 4))

    final_elo         = history[-1][1]
    tier_lbl, tier_col = get_tier(final_elo)
    tk.Label(win, text=f"Current Rating: {final_elo}  ·  {tier_lbl}",
             bg=BG, fg=tier_col, font=('Segoe UI', 11, 'bold')).pack(pady=(0, 8))
    tk.Frame(win, bg=ACCENT, height=2).pack(fill='x', padx=20)

    chart_frame = tk.Frame(win, bg=BG)
    chart_frame.pack(fill='both', expand=True, padx=20, pady=12)

    canvas = tk.Canvas(chart_frame, bg=LOG_BG, highlightthickness=1,
                       highlightbackground='#333')
    canvas.pack(fill='both', expand=True)

    elos = [h[1] for h in history]
    n    = len(history)

    def draw_chart(event=None):
        canvas.delete('all')
        cw = canvas.winfo_width()  or 660
        ch = canvas.winfo_height() or 360
        pad_l, pad_r, pad_t, pad_b = 60, 20, 20, 40
        plot_w = cw - pad_l - pad_r
        plot_h = ch - pad_t - pad_b

        min_elo   = max(0, min(elos) - 50)
        max_elo   = max(elos) + 50
        elo_range = max_elo - min_elo or 1

        # Grid lines
        for i in range(5):
            gy = pad_t + int(plot_h * i / 4)
            canvas.create_line(pad_l, gy, pad_l + plot_w, gy,
                               fill="#222", dash=(4, 4))
            ev = max_elo - int(elo_range * i / 4)
            canvas.create_text(pad_l - 6, gy, text=str(ev),
                               fill="#666", font=('Consolas', 8), anchor='e')
        canvas.create_text(12, ch // 2, text="Elo", fill="#666",
                           font=('Consolas', 8), angle=90)

        def elo_y(e):
            return pad_t + int(plot_h * (1 - (e - min_elo) / elo_range))

        def game_x(i):
            return pad_l + (int(plot_w * i / (n - 1)) if n > 1 else plot_w // 2)

        # Tier zone backgrounds
        for k, (threshold, _, color) in enumerate(RANK_TIERS):
            next_thresh   = RANK_TIERS[k - 1][0] if k > 0 else 9999
            y1_clipped    = pad_t if next_thresh > max_elo else elo_y(min(next_thresh, max_elo))
            y2_clipped    = pad_t + plot_h if threshold < min_elo else elo_y(max(threshold, min_elo))
            if y1_clipped < y2_clipped:
                canvas.create_rectangle(pad_l, y1_clipped, pad_l + plot_w, y2_clipped,
                                        fill=color, stipple='gray12', outline='')

        # Line segments
        points = [(game_x(i), elo_y(e)) for i, (_, e) in enumerate(history)]
        if len(points) > 1:
            for i in range(len(points) - 1):
                _, seg_col = get_tier(int((history[i][1] + history[i + 1][1]) / 2))
                canvas.create_line(points[i][0], points[i][1],
                                   points[i+1][0], points[i+1][1],
                                   fill=seg_col, width=2, smooth=True)

        # Data points
        for i, (_, e) in enumerate(history):
            x, y       = game_x(i), elo_y(e)
            _, pt_col  = get_tier(e)
            canvas.create_oval(x - 4, y - 4, x + 4, y + 4,
                               fill=pt_col, outline='white', width=1)

        # X-axis labels
        step = max(1, n // 8)
        for i in range(0, n, step):
            canvas.create_text(game_x(i), ch - pad_b + 12, text=str(history[i][0]),
                               fill="#555", font=('Consolas', 8))
        canvas.create_text(pad_l + plot_w // 2, ch - 8,
                           text="Game #", fill="#555", font=('Consolas', 8))

        # Start / end annotations
        if history:
            canvas.create_text(game_x(0), elo_y(history[0][1]) - 12,
                               text=str(history[0][1]),
                               fill="#AAA", font=('Consolas', 8))
            canvas.create_text(game_x(n - 1), elo_y(history[-1][1]) - 12,
                               text=str(history[-1][1]),
                               fill=tier_col, font=('Consolas', 9, 'bold'))

    canvas.bind('<Configure>', draw_chart)
    win.after(100, draw_chart)

    # Summary row
    if len(elos) > 1:
        peak    = max(elos)
        lowest  = min(elos)
        change  = elos[-1] - elos[0]
        chg_str = f"+{change}" if change >= 0 else str(change)
        chg_col = "#00FF80" if change >= 0 else "#FF4444"
        summary_f = tk.Frame(win, bg=PANEL_BG)
        summary_f.pack(fill='x', padx=20, pady=(0, 4))
        for label, val, col in [
            ("Peak",   str(peak),   "#FFD700"),
            ("Lowest", str(lowest), "#FF6B6B"),
            ("Change", chg_str,     chg_col),
            ("Games",  str(n),      TEXT),
        ]:
            sf = tk.Frame(summary_f, bg=PANEL_BG)
            sf.pack(side='left', expand=True)
            tk.Label(sf, text=label, bg=PANEL_BG, fg="#666", font=('Segoe UI', 8)).pack()
            tk.Label(sf, text=val,   bg=PANEL_BG, fg=col, font=('Segoe UI', 12, 'bold')).pack()

    tk.Button(win, text="✕ Close", command=win.destroy,
              bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
              padx=20, pady=8, cursor='hand2', relief='flat').pack(pady=(0, 12))


# ═══════════════════════════════════════════════════════════
#  Statistics window
# ═══════════════════════════════════════════════════════════

def show_statistics(root, db):
    """Open the per-engine win/draw/loss statistics window."""
    win = tk.Toplevel(root)
    win.title("Engine Statistics")
    win.configure(bg=BG)
    win.geometry("720x580")

    tk.Label(win, text="📊 ENGINE STATISTICS", bg=BG, fg=ACCENT,
             font=('Segoe UI', 16, 'bold')).pack(pady=(12, 2))
    tk.Label(win, text=f"📁 {db.db_path}", bg=BG, fg="#555",
             font=('Consolas', 8), wraplength=700).pack(pady=(0, 6))

    all_stats   = [None]
    tree_ref    = [None]
    sort_state  = {'col': None, 'reverse': False}

    COL_META = {
        'Engine':   ('engine',   str),
        'Matches':  ('matches',  int),
        'Win':      ('wins',     int),
        'Draw':     ('draws',    int),
        'Lose':     ('loses',    int),
        'WinRate%': ('win_rate', float),
    }

    def _render_rows(stats):
        tree = tree_ref[0]
        if tree is None: return
        for row in tree.get_children():
            tree.delete(row)
        for stat in stats:
            tree.insert('', 'end', values=(
                stat['engine'], stat['matches'], stat['wins'],
                stat['draws'], stat['loses'], f"{stat['win_rate']:.1f}%"))

    def _update_headings():
        tree = tree_ref[0]
        if tree is None: return
        for col in COL_META:
            label = col
            if col == sort_state['col']:
                label += ' ▼' if sort_state['reverse'] else ' ▲'
            tree.heading(col, text=label, command=lambda c=col: sort_by_column(c))

    def sort_by_column(col):
        stats = all_stats[0]
        if not stats: return
        if sort_state['col'] == col:
            sort_state['reverse'] = not sort_state['reverse']
        else:
            sort_state['col']     = col
            sort_state['reverse'] = False
        key_name, _ = COL_META[col]
        all_stats[0] = sorted(stats, key=lambda x: x[key_name],
                              reverse=sort_state['reverse'])
        _render_rows(all_stats[0])
        _update_headings()
        count_lbl.config(text=f"{len(all_stats[0])} engine(s) shown")

    def refresh_stats(query=''):
        stats = db.get_engine_stats(search_query=query)
        if sort_state['col']:
            key_name, _ = COL_META[sort_state['col']]
            stats = sorted(stats, key=lambda x: x[key_name],
                           reverse=sort_state['reverse'])
        all_stats[0] = stats
        _render_rows(stats)
        _update_headings()
        count_lbl.config(text=f"{len(stats)} engine(s) shown")

    # ── Search bar ────────────────────────────────────────
    search_frame = tk.Frame(win, bg=BG)
    search_frame.pack(fill='x', padx=20, pady=(0, 6))
    sb_frame, _ = make_search_bar(search_frame, refresh_stats,
                                   placeholder="🔍 Filter engines…")
    sb_frame.pack(fill='x')

    # ── Treeview ──────────────────────────────────────────
    tree_frame = tk.Frame(win, bg=BG)
    tree_frame.pack(fill='both', expand=True, padx=20, pady=(0, 4))
    scrollbar = tk.Scrollbar(tree_frame)
    scrollbar.pack(side='right', fill='y')

    columns = ('Engine', 'Matches', 'Win', 'Draw', 'Lose', 'WinRate%')
    tree = ttk.Treeview(tree_frame, columns=columns, show='headings',
                        yscrollcommand=scrollbar.set)
    scrollbar.config(command=tree.yview)
    tree_ref[0] = tree
    _apply_tree_style()

    for col, w in [('Engine', 260), ('Matches', 75), ('Win', 55),
                   ('Draw', 55), ('Lose', 55), ('WinRate%', 90)]:
        anchor = 'center' if col != 'Engine' else 'w'
        tree.column(col, width=w, anchor=anchor)
        tree.heading(col, text=col, command=lambda c=col: sort_by_column(c))

    tree.pack(fill='both', expand=True)

    count_lbl = tk.Label(win, text="", bg=BG, fg="#555", font=('Segoe UI', 9))
    count_lbl.pack(pady=(0, 2))

    tk.Label(win, text="💡 Click column header to sort",
             bg=BG, fg="#555", font=('Segoe UI', 9)).pack(pady=(0, 2))

    def on_engine_double_click(event):
        sel = tree.selection()
        if not sel: return
        engine_name = tree.item(sel[0])['values'][0]
        # Show a mini-menu: game history or opening stats
        menu = tk.Menu(win, tearoff=0, bg=BTN_BG, fg=TEXT,
                       activebackground=ACCENT, activeforeground='white',
                       font=('Segoe UI', 10))
        menu.add_command(label="📋  Game History",
                         command=lambda: show_game_history(root, db, filter_engine=engine_name))
        menu.add_command(label="📖  Opening Stats",
                         command=lambda: show_opening_stats(root, db, engine_name))
        try:
            menu.tk_popup(win.winfo_pointerx(), win.winfo_pointery())
        finally:
            menu.grab_release()

    tree.bind('<Double-1>', on_engine_double_click)

    tk.Label(win,
             text="💡 Double-click a row → Game History or Opening Stats",
             bg=BG, fg="#555", font=('Segoe UI', 9)).pack(pady=(0, 2))

    # ── Footer buttons ────────────────────────────────────
    btn_frame = tk.Frame(win, bg=BG)
    btn_frame.pack(fill='x', padx=20, pady=(0, 12))

    shortcuts = tk.Frame(btn_frame, bg=BG)
    shortcuts.pack(side='left')
    tk.Label(shortcuts, text="Sort by:", bg=BG, fg="#888",
             font=('Segoe UI', 8)).pack(side='left', padx=(0, 4))
    for label, col in [("Matches", "Matches"), ("Wins", "Win"), ("Win%", "WinRate%")]:
        tk.Button(shortcuts, text=label, command=lambda c=col: sort_by_column(c),
                  bg=BTN_BG, fg=TEXT, font=('Segoe UI', 8),
                  padx=8, pady=4, cursor='hand2', relief='flat').pack(side='left', padx=2)

    tk.Button(btn_frame, text="🏆 Rankings",
              command=lambda: show_rankings(root, db),
              bg=ACCENT, fg=TEXT, font=('Segoe UI', 10, 'bold'),
              padx=15, pady=8, cursor='hand2', relief='flat').pack(side='left', padx=(10, 5))
    tk.Button(btn_frame, text="📖 All Openings",
              command=lambda: show_opening_stats(root, db, engine_name=None),
              bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
              padx=15, pady=8, cursor='hand2', relief='flat').pack(side='left', padx=5)
    tk.Button(btn_frame, text="View All Game History",
              command=lambda: show_game_history(root, db),
              bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
              padx=15, pady=8, cursor='hand2').pack(side='left', padx=5)
    tk.Button(btn_frame, text="Refresh",
              command=lambda: refresh_stats(''),
              bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
              padx=15, pady=8, cursor='hand2').pack(side='left', padx=5)
    tk.Button(btn_frame, text="Close", command=win.destroy,
              bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
              padx=15, pady=8, cursor='hand2').pack(side='right', padx=5)

    refresh_stats('')


# ═══════════════════════════════════════════════════════════
#  Opening statistics window
# ═══════════════════════════════════════════════════════════

def show_opening_stats(root, db, engine_name=None):
    """
    Show a window with the most common openings for a given engine
    (or for all engines combined if engine_name is None).

    Parameters
    ----------
    root        : tk.Tk | tk.Toplevel
    db          : Database instance
    engine_name : str | None
    """
    if engine_name:
        data  = db.get_opening_stats(engine_name)
        title = f"📖 Opening Stats — {normalize_engine_name(engine_name)}"
    else:
        data  = db.get_opening_stats_all()
        title = "📖 Opening Stats — All Engines"

    win = tk.Toplevel(root)
    win.title(title)
    win.configure(bg=BG)
    win.geometry("900x620")
    win.resizable(True, True)

    # ── Header ────────────────────────────────────────────
    tk.Label(win, text=title, bg=BG, fg=ACCENT,
             font=('Segoe UI', 15, 'bold')).pack(pady=(14, 2))
    tk.Frame(win, bg=ACCENT, height=2).pack(fill='x', padx=20, pady=(4, 8))

    notebook = ttk.Notebook(win)
    notebook.pack(fill='both', expand=True, padx=16, pady=(0, 8))

    style = ttk.Style()
    style.theme_use('clam')
    style.configure('TNotebook', background=BG, borderwidth=0)
    style.configure('TNotebook.Tab', background=BTN_BG, foreground=TEXT,
                    padding=[14, 6], font=('Segoe UI', 10, 'bold'))
    style.map('TNotebook.Tab',
              background=[('selected', ACCENT)],
              foreground=[('selected', 'white')])

    def _build_tab(parent, rows, color_label):
        """Build a treeview tab for one color side."""
        _apply_tree_style()
        columns = ('Opening', 'Games', 'W', 'D', 'L', 'WR%', 'Bar')
        frame = tk.Frame(parent, bg=BG)
        frame.pack(fill='both', expand=True, padx=8, pady=8)

        scroll = tk.Scrollbar(frame)
        scroll.pack(side='right', fill='y')

        tree = ttk.Treeview(frame, columns=columns, show='headings',
                            yscrollcommand=scroll.set)
        scroll.config(command=tree.yview)

        for col, w, anch in [
            ('Opening', 320, 'w'),
            ('Games',    60, 'center'),
            ('W',        50, 'center'),
            ('D',        50, 'center'),
            ('L',        50, 'center'),
            ('WR%',      65, 'center'),
            ('Bar',     200, 'w'),
        ]:
            tree.column(col, width=w, anchor=anch)
            tree.heading(col, text=col)

        tree.tag_configure('top',    foreground='#FFD700')
        tree.tag_configure('good',   foreground='#1BECA0')
        tree.tag_configure('normal', foreground=TEXT)
        tree.tag_configure('losing', foreground='#FF6B6B')

        max_games = rows[0]['games'] if rows else 1
        for i, row in enumerate(rows):
            bar_filled  = int(row['games'] / max_games * 20)
            bar_str     = '█' * bar_filled + '░' * (20 - bar_filled)
            wr          = row['win_rate']
            tag = 'top' if i == 0 else ('good' if wr >= 50 else
                  ('losing' if wr < 35 else 'normal'))
            tree.insert('', 'end', values=(
                row['opening'],
                row['games'],
                row['wins'],
                row['draws'],
                row['losses'],
                f"{wr:.1f}%",
                bar_str,
            ), tags=(tag,))

        tree.pack(fill='both', expand=True)

        if not rows:
            tk.Label(frame, text="No games recorded yet.",
                     bg=BG, fg="#666", font=('Segoe UI', 11)).pack(pady=30)

    # ── As White tab ──────────────────────────────────────
    tab_white = tk.Frame(notebook, bg=BG)
    notebook.add(tab_white, text="  ♔  As White  ")
    _build_tab(tab_white, data.get('as_white', []), 'white')

    # ── As Black tab ──────────────────────────────────────
    tab_black = tk.Frame(notebook, bg=BG)
    notebook.add(tab_black, text="  ♚  As Black  ")
    _build_tab(tab_black, data.get('as_black', []), 'black')

    # ── Summary stats ─────────────────────────────────────
    summary_frame = tk.Frame(win, bg=PANEL_BG)
    summary_frame.pack(fill='x', padx=16, pady=(0, 4))

    white_rows = data.get('as_white', [])
    black_rows = data.get('as_black', [])
    total_w = sum(r['games'] for r in white_rows)
    total_b = sum(r['games'] for r in black_rows)

    fav_w = white_rows[0]['opening'] if white_rows else "—"
    fav_b = black_rows[0]['opening'] if black_rows else "—"

    for label, val, col in [
        ("White games:", str(total_w), "#FFD700"),
        ("Fav. as White:", fav_w[:30] + ("…" if len(fav_w) > 30 else ""), "#FFD700"),
        ("Black games:", str(total_b), "#C8C8C8"),
        ("Fav. as Black:", fav_b[:30] + ("…" if len(fav_b) > 30 else ""), "#C8C8C8"),
    ]:
        f = tk.Frame(summary_frame, bg=PANEL_BG)
        f.pack(side='left', expand=True, padx=8, pady=6)
        tk.Label(f, text=label, bg=PANEL_BG, fg="#666",
                 font=('Segoe UI', 8)).pack()
        tk.Label(f, text=val, bg=PANEL_BG, fg=col,
                 font=('Segoe UI', 9, 'bold'), wraplength=180).pack()

    tk.Button(win, text="✕ Close", command=win.destroy,
              bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
              padx=20, pady=8, cursor='hand2', relief='flat').pack(pady=(0, 12))


# ═══════════════════════════════════════════════════════════
#  Game history window
# ═══════════════════════════════════════════════════════════

def show_game_history(root, db, filter_engine=None, opening_book=None):
    """Open the game-history browser window."""
    norm_filter = normalize_engine_name(filter_engine) if filter_engine else None

    win = tk.Toplevel(root)
    win.title(f"Game History{' — ' + norm_filter if norm_filter else ''}")
    win.configure(bg=BG)
    win.geometry("1000x640")

    header_frame = tk.Frame(win, bg=BG)
    header_frame.pack(fill='x', padx=20, pady=(12, 0))
    tk.Label(header_frame, text="📜 GAME HISTORY", bg=BG, fg=ACCENT,
             font=('Segoe UI', 16, 'bold')).pack(side='left')
    if norm_filter:
        tk.Label(header_frame, text=f"  ·  {norm_filter}", bg=BG, fg="#FFD700",
                 font=('Segoe UI', 11)).pack(side='left')
        tk.Button(header_frame, text="✕ Clear Filter",
                  command=lambda: [win.destroy(),
                                   show_game_history(root, db, opening_book=opening_book)],
                  bg=BTN_BG, fg=TEXT, font=('Segoe UI', 9), padx=10, pady=4,
                  cursor='hand2', relief='flat').pack(side='right')

    # ── Source filter row ─────────────────────────────────
    filter_row = tk.Frame(win, bg=BG)
    filter_row.pack(fill='x', padx=20, pady=(4, 0))
    tk.Label(filter_row, text="Show:", bg=BG, fg="#888",
             font=('Segoe UI', 8)).pack(side='left')
    source_filter_var = tk.StringVar(value='all')
    for val, lbl in [('all', 'All Games'), ('regular', '🎮 Regular'), ('tournament', '🏆 Tournament')]:
        tk.Radiobutton(filter_row, text=lbl, variable=source_filter_var,
                       value=val, bg=BG, fg="#AAA",
                       selectcolor=BTN_BG, activebackground=BG,
                       font=('Segoe UI', 8),
                       command=lambda: refresh_history('')
                       ).pack(side='left', padx=6)

    search_container = tk.Frame(win, bg=BG)
    search_container.pack(fill='x', padx=20, pady=(4, 4))

    all_games_cache = [None]
    tree_ref2       = [None]
    count_lbl2      = [None]

    def refresh_history(query=''):
        src = source_filter_var.get()
        source_arg = src if src != 'all' else None
        games = db.get_all_games(
            filter_engine=filter_engine,
            search_query=query,
            source_filter=source_arg,
        )
        all_games_cache[0] = games
        tree = tree_ref2[0]
        if tree is None: return
        for row in tree.get_children():
            tree.delete(row)

        for game in games:
            # ── Use helper to safely unpack regardless of column count ──
            (game_id, white, black, result, reason,
             date, time_str, moves, duration, source) = _unpack_game_row(game)

            duration_str = f"{duration//60}m {duration%60}s" if duration else "N/A"

            # Source badge shown in the Reason column prefix
            src_badge = "🏆 " if source == 'tournament' else ""

            if result == '1/2-1/2':
                tag = 'draw'
            elif result == '1-0':
                tag = 'loss' if (norm_filter and normalize_engine_name(black) == norm_filter) \
                      else 'white_win'
            elif result == '0-1':
                tag = 'loss' if (norm_filter and normalize_engine_name(white) == norm_filter) \
                      else 'black_win'
            else:
                tag = ''

            tree.insert('', 'end',
                        values=(game_id, date, time_str, white, black,
                                result, f"{src_badge}{reason}", moves or 0, duration_str),
                        tags=(tag,))

        if count_lbl2[0]:
            count_lbl2[0].config(text=f"{len(games)} game(s) shown")

    sb_frame2, _ = make_search_bar(search_container, refresh_history,
                                    placeholder="🔍 Search by engine, result, reason, date…")
    sb_frame2.pack(fill='x')

    # ── Treeview ──────────────────────────────────────────
    tree_frame = tk.Frame(win, bg=BG)
    tree_frame.pack(fill='both', expand=True, padx=20, pady=(4, 0))
    scrollbar = tk.Scrollbar(tree_frame)
    scrollbar.pack(side='right', fill='y')

    columns = ('ID', 'Date', 'Time', 'White', 'Black',
               'Result', 'Reason', 'Moves', 'Duration')
    tree = ttk.Treeview(tree_frame, columns=columns, show='headings',
                        yscrollcommand=scrollbar.set)
    scrollbar.config(command=tree.yview)
    tree_ref2[0] = tree
    _apply_tree_style()

    for col, w in [('ID', 40), ('Date', 80), ('Time', 70), ('White', 150),
                   ('Black', 150), ('Result', 60), ('Reason', 170),
                   ('Moves', 50), ('Duration', 80)]:
        anchor = 'center' if col not in ('White', 'Black', 'Reason') else 'w'
        tree.heading(col, text=col)
        tree.column(col, width=w, anchor=anchor)

    tree.tag_configure('white_win', foreground='#FFD700')
    tree.tag_configure('black_win', foreground='#C8C8C8')
    tree.tag_configure('draw',      foreground='#00BFFF')
    tree.tag_configure('loss',      foreground='#FF4444')
    tree.pack(fill='both', expand=True)

    count_lbl2[0] = tk.Label(win, text="", bg=BG, fg="#555", font=('Segoe UI', 9))
    count_lbl2[0].pack(pady=(2, 0))
    tk.Label(win,
             text="💡 Double-click row to view PGN  |  Click White/Black cell to filter by engine  |  🏆 = Tournament game",
             bg=BG, fg="#444", font=('Segoe UI', 8)).pack(pady=(0, 4))

    def _on_tree_click(event, double=False):
        region = tree.identify_region(event.x, event.y)
        if region != 'cell': return
        col_id    = tree.identify_column(event.x)
        row_id    = tree.identify_row(event.y)
        if not row_id: return
        col_index = int(col_id.replace('#', '')) - 1
        values    = tree.item(row_id)['values']
        if double:
            pgn = db.get_game_pgn(values[0])
            if pgn:
                show_pgn_viewer(root, db, pgn, values, all_games_cache[0] or [],
                                opening_book=opening_book)
            else:
                messagebox.showerror("Error", "Could not load PGN.")
        else:
            if col_index == 3:
                win.destroy()
                show_game_history(root, db, filter_engine=values[3],
                                  opening_book=opening_book)
            elif col_index == 4:
                win.destroy()
                show_game_history(root, db, filter_engine=values[4],
                                  opening_book=opening_book)

    tree.bind('<Button-1>', lambda e: _on_tree_click(e, double=False))
    tree.bind('<Double-1>', lambda e: _on_tree_click(e, double=True))

    btn_frame = tk.Frame(win, bg=BG)
    btn_frame.pack(fill='x', padx=20, pady=(4, 12))

    def view_pgn():
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("No Selection", "Please select a game."); return
        values = tree.item(sel[0])['values']
        pgn = db.get_game_pgn(values[0])
        if pgn:
            show_pgn_viewer(root, db, pgn, values, all_games_cache[0] or [],
                            opening_book=opening_book)
        else:
            messagebox.showerror("Error", "Could not load PGN.")

    tk.Button(btn_frame, text="View PGN", command=view_pgn, bg=ACCENT, fg=TEXT,
              font=('Segoe UI', 10, 'bold'), padx=15, pady=8,
              cursor='hand2').pack(side='left', padx=5)
    if norm_filter:
        tk.Button(btn_frame, text="Show All Games",
                  command=lambda: [win.destroy(),
                                   show_game_history(root, db, opening_book=opening_book)],
                  bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10), padx=15, pady=8,
                  cursor='hand2').pack(side='left', padx=5)
    tk.Button(btn_frame, text="Refresh",
              command=lambda: refresh_history(''),
              bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10), padx=15, pady=8,
              cursor='hand2').pack(side='left', padx=5)
    tk.Button(btn_frame, text="Close", command=win.destroy,
              bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10), padx=15, pady=8,
              cursor='hand2').pack(side='right', padx=5)

    refresh_history('')


# ═══════════════════════════════════════════════════════════
#  PGN viewer
# ═══════════════════════════════════════════════════════════

def _parse_pgn_moves(pgn):
    """Extract a list of UCI move strings from a PGN text."""
    import re
    lines = pgn.split('\n')
    moves_text = []
    in_headers = True
    for line in lines:
        line = line.strip()
        if not line:
            in_headers = False; continue
        if in_headers and line.startswith('['): continue
        moves_text.append(line)

    full_text = ' '.join(moves_text)
    for result_token in ['1-0', '0-1', '1/2-1/2', '*']:
        full_text = full_text.replace(result_token, '')
    full_text = re.sub(r'\d+\.', '', full_text)
    san_moves = full_text.split()

    temp_board = Board()
    uci_moves  = []
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
            print(f"[_parse_pgn_moves] Error on {san}: {e}")
    return uci_moves


from core.constants import LIGHT_SQ, DARK_SQ, LAST_FROM, LAST_TO, CHECK_SQ, UNICODE


def show_pgn_viewer(root, db, pgn, game_info, all_games, opening_book=None):
    """Open the interactive PGN game replay viewer."""
    win = tk.Toplevel(root)
    win.title(f"PGN Viewer - Game #{game_info[0]}")
    win.configure(bg=BG)
    win.geometry("1000x700")

    current_game_id = game_info[0]
    current_index   = next((i for i, g in enumerate(all_games)
                            if _unpack_game_row(g)[0] == current_game_id), None)

    def load_game(direction):
        if current_index is None: return
        new_index = current_index + direction
        if 0 <= new_index < len(all_games):
            game    = all_games[new_index]
            new_pgn = db.get_game_pgn(_unpack_game_row(game)[0])
            if new_pgn:
                win.destroy()
                (gid, white, black, result, reason,
                 date, time_str, moves, duration, source) = _unpack_game_row(game)
                duration_str = f"{duration//60}m {duration%60}s" if duration else "N/A"
                show_pgn_viewer(root, db, new_pgn,
                                (gid, date, time_str, white, black,
                                 result, reason, moves, duration_str),
                                all_games, opening_book=opening_book)

    # ── Navigation header ─────────────────────────────────
    top_nav = tk.Frame(win, bg=PANEL_BG)
    top_nav.pack(fill='x', padx=10, pady=(10, 5))

    tk.Button(top_nav, text="◀ Previous Game",
              command=lambda: load_game(-1),
              bg=BTN_BG, fg=TEXT, font=('Segoe UI', 9, 'bold'),
              padx=10, pady=5, cursor='hand2', relief='flat',
              state='normal' if current_index and current_index > 0 else 'disabled'
              ).pack(side='left', padx=5)

    tk.Label(top_nav,
             text=f"Game {current_index + 1 if current_index is not None else '?'} of {len(all_games)}",
             bg=PANEL_BG, fg=ACCENT, font=('Segoe UI', 10, 'bold')
             ).pack(side='left', expand=True)

    tk.Button(top_nav, text="Next Game ▶",
              command=lambda: load_game(1),
              bg=BTN_BG, fg=TEXT, font=('Segoe UI', 9, 'bold'),
              padx=10, pady=5, cursor='hand2', relief='flat',
              state='normal' if current_index is not None
                    and current_index < len(all_games) - 1 else 'disabled'
              ).pack(side='right', padx=5)

    # ── Left column: board + controls ─────────────────────
    main_container = tk.Frame(win, bg=BG)
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
    tk.Label(info_frame, text=f"Result: {game_info[5]} - {game_info[6]}",
             bg=PANEL_BG, fg=TEXT, font=('Segoe UI', 10)).pack(anchor='w', padx=10, pady=(0, 5))

    # ── Board canvas ──────────────────────────────────────
    board_frame = tk.Frame(left_frame, bg=BG)
    board_frame.pack(pady=10)

    replay_board = Board()
    replay_size  = 60
    replay_canvas = tk.Canvas(board_frame,
                               width=replay_size * 8, height=replay_size * 8,
                               bg=BG, bd=0, highlightthickness=2,
                               highlightcolor=ACCENT, highlightbackground='#333')
    replay_canvas.pack()

    moves_list         = _parse_pgn_moves(pgn)
    current_move_index = [0]

    replay_opening_var = tk.StringVar(value="")
    tk.Label(left_frame, textvariable=replay_opening_var,
             bg=BG, fg="#00BFFF", font=('Segoe UI', 9, 'italic'),
             anchor='center').pack(fill='x', padx=4)

    def _update_replay_opening():
        if opening_book and opening_book.loaded:
            eco, name = opening_book.lookup(replay_board.uci_moves_list())
            if name:
                replay_opening_var.set(f"📖 {eco}  ·  {name}" if eco else f"📖 {name}")
            else:
                replay_opening_var.set("")

    def draw_replay_board(highlight_move=None):
        replay_canvas.delete('all')
        lm_from = lm_to = None
        if highlight_move and len(highlight_move) >= 4:
            lm_from = (8 - int(highlight_move[1]), ord(highlight_move[0]) - ord('a'))
            lm_to   = (8 - int(highlight_move[3]), ord(highlight_move[2]) - ord('a'))
        for row in range(8):
            for col in range(8):
                light = (row + col) % 2 == 0
                color = LIGHT_SQ if light else DARK_SQ
                if lm_from and (row, col) == lm_from: color = LAST_FROM
                elif lm_to  and (row, col) == lm_to:  color = LAST_TO
                x1, y1 = col * replay_size, row * replay_size
                x2, y2 = x1 + replay_size, y1 + replay_size
                replay_canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline='')
                pc = replay_board.get(row, col)
                if pc and pc != '.':
                    sym = UNICODE.get(pc, pc)
                    fg  = '#F5F5F5' if pc.isupper() else '#1A1A1A'
                    sh  = '#000000' if pc.isupper() else '#888888'
                    fsz = int(replay_size * 0.60)
                    cx, cy = x1 + replay_size // 2, y1 + replay_size // 2
                    replay_canvas.create_text(cx+1, cy+2, text=sym, font=('Segoe UI', fsz), fill=sh)
                    replay_canvas.create_text(cx,   cy,   text=sym, font=('Segoe UI', fsz), fill=fg)
        replay_canvas.create_rectangle(0, 0, replay_size * 8, replay_size * 8,
                                        outline='#555', width=1)
        _update_replay_opening()

    move_label = tk.Label(left_frame, text="Start position", bg=BG, fg=ACCENT,
                          font=('Segoe UI', 11, 'bold'))
    move_label.pack(pady=10)

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
        draw_replay_board(moves_list[-1] if moves_list else None)
        update_move_label()

    def prev_move():
        if current_move_index[0] > 0:
            replay_board.reset(); current_move_index[0] -= 1
            for i in range(current_move_index[0]):
                try: replay_board.apply_uci(moves_list[i])
                except: break
            last = moves_list[current_move_index[0] - 1] if current_move_index[0] > 0 else None
            draw_replay_board(last); update_move_label()

    def next_move():
        if current_move_index[0] < len(moves_list):
            try:
                move = moves_list[current_move_index[0]]
                replay_board.apply_uci(move)
                current_move_index[0] += 1
                draw_replay_board(move); update_move_label()
            except Exception as e:
                messagebox.showerror("Error", f"Invalid move: {e}")

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

    for key in ('<Left>', '<Right>', '<Home>', '<End>', '<Prior>', '<Next>'):
        win.bind(key, on_key)

    tk.Label(left_frame, text="⌨ Move: ←→ | Start/End: Home/End | Game: PgUp/PgDn",
             bg=BG, fg="#666", font=('Segoe UI', 8)).pack(pady=5)

    # ── Right column: PGN text ────────────────────────────
    right_frame = tk.Frame(main_container, bg=BG)
    right_frame.pack(side='right', fill='both', expand=True)

    tk.Label(right_frame, text="PGN Notation", bg=BG, fg=ACCENT,
             font=('Segoe UI', 12, 'bold')).pack(pady=(0, 5))

    text_frame = tk.Frame(right_frame, bg=LOG_BG,
                          highlightthickness=1, highlightbackground='#333')
    text_frame.pack(fill='both', expand=True, pady=(0, 10))
    pgn_text = scrolledtext.ScrolledText(
        text_frame, bg=LOG_BG, fg=TEXT,
        font=('Consolas', 10), relief='flat',
        padx=10, pady=10, wrap='word')
    pgn_text.pack(fill='both', expand=True)
    pgn_text.insert('1.0', pgn)
    pgn_text.config(state='disabled')

    btn_frame2 = tk.Frame(right_frame, bg=BG)
    btn_frame2.pack(fill='x', pady=(0, 10))

    def copy_pgn():
        win.clipboard_clear(); win.clipboard_append(pgn)
        messagebox.showinfo("Copied", "PGN copied to clipboard!")

    def export_pgn():
        path = filedialog.asksaveasfilename(
            defaultextension=".pgn",
            filetypes=[("PGN", "*.pgn"), ("All", "*.*")],
            title="Export PGN")
        if path:
            with open(path, 'w') as f:
                f.write(pgn)
            messagebox.showinfo("Saved", f"PGN exported to:\n{path}")

    tk.Button(btn_frame2, text="Copy PGN", command=copy_pgn,
              bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
              padx=15, pady=8, cursor='hand2').pack(side='left', padx=5)
    tk.Button(btn_frame2, text="Export PGN", command=export_pgn,
              bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
              padx=15, pady=8, cursor='hand2').pack(side='left', padx=5)
    tk.Button(btn_frame2, text="Close", command=win.destroy,
              bg=BTN_BG, fg=TEXT, font=('Segoe UI', 10),
              padx=15, pady=8, cursor='hand2').pack(side='right', padx=5)

    draw_replay_board()
    update_move_label()