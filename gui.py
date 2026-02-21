# ═══════════════════════════════════════════════════════════
#  gui.py — Main ChessGUI application class
# ═══════════════════════════════════════════════════════════

import os
import sys
import threading
import time
from datetime import datetime
from tkinter import filedialog, messagebox, scrolledtext
import tkinter as tk
from tkinter import ttk

from constants import (
    BG, PANEL_BG, ACCENT, TEXT, BTN_BG, BTN_HOV,
    LOG_BG, INFO_BG, LIGHT_SQ, DARK_SQ, LAST_FROM, LAST_TO, CHECK_SQ,
    UNICODE, QUALITY_COLORS, RANK_TIERS,
)
from utils import (
    normalize_engine_name, get_db_path, get_tier,
    classify_move_quality, build_pgn,
)
from elo import compute_elo_ratings
from board import Board
from engine import UCIEngine, AnalyzerEngine
from opening_book import OpeningBook
from database import Database
from dialogs import ask_promotion, ask_stop_result, make_search_bar
from views import (
    show_rankings, show_elo_history,
    show_statistics, show_game_history, show_pgn_viewer,
)


class ChessGUI:
    """
    Main application window for Chess Engine Arena.

    Supports:
    - Engine vs Engine mode
    - Human vs Engine mode
    - Full move-quality analysis via an optional Stockfish analyzer
    - Eval bar, opening-book display, Elo banners
    - Integrated SQLite database with rankings, statistics, and PGN viewer
    """

    def __init__(self, root,
                 preloaded_book=None,
                 preloaded_book_path=None,
                 preloaded_analyzer=None,
                 preloaded_analyzer_path=None):

        self.root = root
        self.root.title("♟  Chess Engine Arena — Enhanced")
        self.root.configure(bg=BG)
        self.root.resizable(True, True)
        self.root.minsize(1120, 860)
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

        # ── Core state ────────────────────────────────────
        self.board   = Board()
        self.engine1 = None
        self.engine2 = None

        self._analyzer_lock = threading.Lock()
        self._last_eval_cp  = None
        self._last_quality  = None
        self._move_qualities = []

        # ── Opening book ──────────────────────────────────
        if preloaded_book and preloaded_book.loaded:
            self.opening_book      = preloaded_book
            self._opening_csv_path = preloaded_book_path
        else:
            self.opening_book      = OpeningBook()
            self._opening_csv_path = None

        # ── Analyzer engine ───────────────────────────────
        self._analyzer_path = preloaded_analyzer_path
        if preloaded_analyzer and preloaded_analyzer.alive:
            self.analyzer = preloaded_analyzer
        else:
            self.analyzer = None

        # ── Tk variables ──────────────────────────────────
        self.e1_path   = tk.StringVar()
        self.e2_path   = tk.StringVar()
        self.e1_name   = tk.StringVar(value="Engine 1 (Black)")
        self.e2_name   = tk.StringVar(value="Engine 2 (White)")
        self.movetime  = tk.IntVar(value=1000)
        self.delay     = tk.DoubleVar(value=0.5)

        self.play_mode    = tk.StringVar(value="engine_vs_engine")
        self.player_name  = tk.StringVar(value="Player")
        self.player_color = tk.StringVar(value="white")

        self.e1_eval  = tk.StringVar(value='—')
        self.e2_eval  = tk.StringVar(value='—')
        self.e1_depth = tk.StringVar(value='—')
        self.e2_depth = tk.StringVar(value='—')

        self.opening_var = tk.StringVar(value="")

        # ── Game state ────────────────────────────────────
        self.game_running   = False
        self.game_paused    = False
        self.game_thread    = None
        self.last_move      = None
        self.game_result    = ''
        self.game_date      = ''
        self.sq_size        = 74
        self.flipped        = False
        self._pending_b     = None
        self.board_lock     = threading.Lock()
        self._engine_thinking = False
        self._eval_bar_cp   = 0
        self.current_opening_name = None

        # ── Database ──────────────────────────────────────
        self.db = Database()

        # ── Build UI ──────────────────────────────────────
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
            f"DB: {self.db.db_path} | {book_status} | "
            f"Ready — load engines and press ▶ Start")

        self.root.after(100, self._draw_eval_bar, 0)
        self.root.after(300, self._refresh_banners)

    # ═══════════════════════════════════════════════════════
    #  Window lifecycle
    # ═══════════════════════════════════════════════════════

    def _on_closing(self):
        self.game_running     = False
        self.game_paused      = False
        self._engine_thinking = False

        def _shutdown():
            try: self._kill_engines()
            except: pass
            if self.analyzer:
                try: self.analyzer.stop()
                except: pass

        threading.Thread(target=_shutdown, daemon=True).start()
        self.root.after(300, self.root.destroy)

    # ═══════════════════════════════════════════════════════
    #  Eval bar
    # ═══════════════════════════════════════════════════════

    def _draw_eval_bar(self, cp=None):
        if cp is not None:
            self._eval_bar_cp = cp
        self.eval_canvas.delete('all')

        bar_h = self.eval_canvas.winfo_height() or 592
        bar_w = self.eval_canvas.winfo_width()  or 20

        import math
        cp_val  = max(-1000, min(1000, self._eval_bar_cp))
        ratio   = 0.5 + 0.5 * math.tanh(cp_val / 400.0)
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
            ty = max(black_h - 10, 8);  fg = "#EEE"
        else:
            ty = min(black_h + 10, bar_h - 8); fg = "#222"

        self.eval_canvas.create_text(bar_w//2, ty, text=txt,
                                      font=('Consolas', 7, 'bold'),
                                      fill=fg, anchor='center')
        self.eval_canvas.create_rectangle(0, 0, bar_w-1, bar_h-1,
                                           outline="#555", width=1)

    # ═══════════════════════════════════════════════════════
    #  Move quality analysis
    # ═══════════════════════════════════════════════════════

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
            self.quality_lbl.config(text="", bg=BG); return
        color = QUALITY_COLORS.get(quality, TEXT)
        self.quality_lbl.config(text=quality, fg=color, bg=BG)

    def _trigger_quality_analysis(self, moves_before, moves_after, was_white, san):
        if not self.analyzer or not self.analyzer.alive:
            return
        threading.Thread(
            target=self._analyze_move_quality,
            args=(moves_before, moves_after, was_white, san),
            daemon=True).start()

    # ═══════════════════════════════════════════════════════
    #  Opening book helpers
    # ═══════════════════════════════════════════════════════

    def _refresh_opening(self):
        if not self.opening_book or not self.opening_book.loaded:
            return
        eco, name = self.opening_book.lookup(self.board.uci_moves_list())
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
                messagebox.showerror("Error", f"No valid openings found in:\n{path}"); return
            self.opening_book      = book
            self._opening_csv_path = path
            self._update_book_lbl()
            self._reset_opening()
            messagebox.showinfo("Loaded",
                f"✓ {len(book._entries)} openings loaded from:\n{os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load CSV:\n{e}")

    # ═══════════════════════════════════════════════════════
    #  Analyzer helpers
    # ═══════════════════════════════════════════════════════

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
        if not self._analyzer_path: return
        try:
            eng = AnalyzerEngine(self._analyzer_path, "Analyzer")
            eng.start()
            self.analyzer = eng
            self._update_analyzer_lbl()
        except Exception as e:
            print(f"[Analyzer] Failed: {e}")
            self.analyzer = None
            self._update_analyzer_lbl()

    def _update_analyzer_lbl(self):
        if not hasattr(self, 'analyzer_lbl'): return
        if self.analyzer and self.analyzer.alive:
            name = os.path.basename(self._analyzer_path) if self._analyzer_path else "?"
            self.analyzer_lbl.config(text=f"🔍 {name}", fg="#1BECA0")
        else:
            self.analyzer_lbl.config(text="⚠ No analyzer", fg="#FF8800")

    # ═══════════════════════════════════════════════════════
    #  View launchers (delegate to views module)
    # ═══════════════════════════════════════════════════════

    def _show_rankings(self):
        show_rankings(self.root, self.db)

    def _show_elo_history(self, engine_name):
        show_elo_history(self.root, self.db, engine_name)

    def _show_statistics(self):
        show_statistics(self.root, self.db)

    def _show_game_history(self, filter_engine=None):
        show_game_history(self.root, self.db,
                          filter_engine=filter_engine,
                          opening_book=self.opening_book)

    def _tournament(self):
        """Open the tournament setup dialog, passing the GUI's preloaded
        analyzer engine and opening book so they are auto-attached."""
        try:
            from tournament_module import open_tournament
            open_tournament(
                self.root,
                db_path      = self.db.db_path,
                analyzer     = self.analyzer,        # live AnalyzerEngine from LoadingScreen
                opening_book = self.opening_book,    # OpeningBook from LoadingScreen
            )
        except ImportError:
            messagebox.showinfo("Tournament",
                "tournament_module.py not found in the same directory.")

    # ═══════════════════════════════════════════════════════
    #  UI builders
    # ═══════════════════════════════════════════════════════

    def _build_ui(self):
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        lp = tk.Frame(self.root, bg=PANEL_BG, width=270)
        lp.grid(row=0, column=0, sticky='nsew', padx=(8, 0), pady=8)
        lp.grid_propagate(False)
        self._build_left(lp)

        cp = tk.Frame(self.root, bg=BG)
        cp.grid(row=0, column=1, sticky='nsew', padx=8, pady=8)
        cp.columnconfigure(1, weight=1)
        cp.rowconfigure(0, weight=1)
        self._build_center(cp)

        rp = tk.Frame(self.root, bg=PANEL_BG, width=285)
        rp.grid(row=0, column=2, sticky='nsew', padx=(0, 8), pady=8)
        rp.grid_propagate(False)
        self._build_right(rp)

    # ── Widget factory helpers ────────────────────────────

    def _lbl(self, p, txt, sz=10, bold=False, fg=TEXT, bg=PANEL_BG, anchor='w'):
        return tk.Label(p, text=txt, bg=bg, fg=fg, anchor=anchor,
                        font=('Segoe UI', sz, 'bold' if bold else 'normal'))

    def _btn(self, p, txt, cmd, accent=False, small=False):
        bg2 = ACCENT if accent else BTN_BG
        b = tk.Button(p, text=txt, command=cmd, bg=bg2, fg=TEXT,
                      activebackground=BTN_HOV, activeforeground='white',
                      relief='flat',
                      font=('Segoe UI', 8 if small else 10, 'normal'),
                      padx=4, pady=2 if small else 5, cursor='hand2', borderwidth=0)
        b.bind('<Enter>', lambda e: b.config(bg=BTN_HOV))
        b.bind('<Leave>', lambda e: b.config(bg=bg2))
        return b

    def _entry(self, p, var, fg=TEXT, width=None):
        kw = dict(textvariable=var, bg=LOG_BG, fg=fg, insertbackground=TEXT,
                  font=('Consolas', 8), relief='flat', highlightthickness=1,
                  highlightcolor=ACCENT, highlightbackground='#333')
        if width: kw['width'] = width
        return tk.Entry(p, **kw)

    # ── Left panel ────────────────────────────────────────

    def _build_left(self, p):
        tk.Label(p, text="ENGINE ARENA", bg=PANEL_BG, fg=ACCENT,
                 font=('Segoe UI', 13, 'bold')).pack(pady=(16, 4))
        tk.Frame(p, bg=ACCENT, height=2).pack(fill='x', padx=10, pady=2)

        # Play mode radio buttons
        mode_frame = tk.Frame(p, bg=PANEL_BG)
        mode_frame.pack(fill='x', padx=10, pady=(8, 4))
        tk.Label(mode_frame, text="PLAY MODE:", bg=PANEL_BG, fg=ACCENT,
                 font=('Segoe UI', 9, 'bold')).pack(anchor='w')
        for label, value in [("Engine vs Engine", "engine_vs_engine"),
                              ("Play vs Engine",   "human_vs_engine")]:
            tk.Radiobutton(mode_frame, text=label, variable=self.play_mode, value=value,
                           bg=PANEL_BG, fg=TEXT, selectcolor=BTN_BG,
                           activebackground=PANEL_BG, activeforeground=TEXT,
                           font=('Segoe UI', 9),
                           command=self._on_mode_change).pack(anchor='w', pady=2)

        tk.Frame(p, bg='#2a2a4a', height=1).pack(fill='x', padx=10, pady=6)
        self.config_frame = tk.Frame(p, bg=PANEL_BG)
        self.config_frame.pack(fill='x', padx=10)
        self._build_config_ui()

        tk.Frame(p, bg='#2a2a4a', height=1).pack(fill='x', padx=10, pady=6)
        self._lbl(p, "⚙ SETTINGS", 9, bold=True, fg=ACCENT).pack(fill='x', padx=10)
        for lbl, var, frm, to, inc, fmt in [
            ("Move time (ms):", self.movetime, 100, 60000, 100,  None),
            ("Move delay (s):",  self.delay,   0.0,  10.0, 0.1, '%.1f'),
        ]:
            rf = tk.Frame(p, bg=PANEL_BG); rf.pack(fill='x', padx=10, pady=2)
            self._lbl(rf, lbl, 8).pack(side='left')
            kw = dict(from_=frm, to=to, increment=inc, textvariable=var, width=7,
                      bg=LOG_BG, fg=TEXT, buttonbackground=BTN_BG,
                      font=('Consolas', 8), relief='flat', insertbackground=TEXT)
            if fmt: kw['format'] = fmt
            tk.Spinbox(rf, **kw).pack(side='right')

        tk.Frame(p, bg='#2a2a4a', height=1).pack(fill='x', padx=10, pady=6)
        for txt, cmd, acc in [
            ("▶  START GAME",      self._start_game,       True),
            ("⏸  PAUSE / RESUME",  self._toggle_pause,     False),
            ("⏹  STOP GAME",       self._stop_game,        False),
            ("↺  NEW GAME",        self._new_game,         False),
            ("⇅  FLIP BOARD",      self._flip_board,       False),
            ("💾  EXPORT PGN",     self._export_pgn,       False),
            ("🏆  RANKINGS",       self._show_rankings,    False),
            ("🏆  TOURNAMENT",     self._tournament,       False),
            ("📊  STATISTICS",     self._show_statistics,  False),
        ]:
            self._btn(p, txt, cmd, accent=acc).pack(fill='x', padx=10, pady=2)

        tk.Frame(p, bg='#2a2a4a', height=1).pack(fill='x', padx=10, pady=4)
        self._lbl(p, "Material balance", 8, fg="#888").pack(fill='x', padx=10)
        self.mat_lbl = tk.Label(p, text="=", bg=PANEL_BG, fg=TEXT,
                                 font=('Consolas', 9), anchor='center')
        self.mat_lbl.pack(fill='x', padx=10)

        tk.Frame(p, bg='#2a2a4a', height=1).pack(fill='x', padx=10, pady=4)
        self.book_lbl = tk.Label(p, text="", bg=PANEL_BG, fg="#00BFFF",
                                  font=('Segoe UI', 7), anchor='w', wraplength=240)
        self.book_lbl.pack(fill='x', padx=10)
        self._btn(p, "📂  Load Openings CSV", self._browse_csv,
                  small=True).pack(fill='x', padx=10, pady=2)

        tk.Frame(p, bg='#2a2a4a', height=1).pack(fill='x', padx=10, pady=4)
        self._lbl(p, "🔍 ANALYZER (Stockfish)", 8, bold=True, fg=ACCENT).pack(fill='x', padx=10)
        self.analyzer_lbl = tk.Label(p, text="⚠ No analyzer", bg=PANEL_BG, fg="#FF8800",
                                      font=('Segoe UI', 7), anchor='w', wraplength=240)
        self.analyzer_lbl.pack(fill='x', padx=10)
        self._btn(p, "📂  Load Analyzer", self._browse_analyzer,
                  small=True).pack(fill='x', padx=10, pady=2)

    def _build_config_ui(self):
        for widget in self.config_frame.winfo_children():
            widget.destroy()

        if self.play_mode.get() == "engine_vs_engine":
            for col, path_var, name_var, eval_var, dep_var, tag, color in [
                ('BLACK  ♚', 'e1_path', 'e1_name', 'e1_eval', 'e1_depth', 1, "#C8C8C8"),
                ('WHITE  ♔', 'e2_path', 'e2_name', 'e2_eval', 'e2_depth', 2, "#FFD700"),
            ]:
                pv = getattr(self, path_var); nv = getattr(self, name_var)
                ev = getattr(self, eval_var); dv = getattr(self, dep_var)
                self._lbl(self.config_frame, f"◈ {col}", 9, bold=True, fg=color).pack(fill='x', pady=(10, 2))
                rf = tk.Frame(self.config_frame, bg=PANEL_BG); rf.pack(fill='x', pady=2)
                self._entry(rf, pv).pack(side='left', fill='x', expand=True, ipady=4)
                self._btn(rf, "…", lambda t=tag: self._browse(t), small=True).pack(side='right', padx=(4, 0))
                self._entry(self.config_frame, nv, fg=color).pack(fill='x', pady=2, ipady=3)
                ef = tk.Frame(self.config_frame, bg=INFO_BG); ef.pack(fill='x', pady=2)
                self._lbl(ef, "Eval:", 8, bg=INFO_BG, fg="#888").pack(side='left', padx=4)
                tk.Label(ef, textvariable=ev, bg=INFO_BG, fg="#7FFF00",
                         font=('Consolas', 8)).pack(side='left')
                self._lbl(ef, " D:", 8, bg=INFO_BG, fg="#888").pack(side='left')
                tk.Label(ef, textvariable=dv, bg=INFO_BG, fg="#7FFF00",
                         font=('Consolas', 8)).pack(side='left')
                tk.Frame(self.config_frame, bg='#2a2a4a', height=1).pack(fill='x', pady=4)
        else:
            self._lbl(self.config_frame, "◈ PLAYER INFO", 9, bold=True, fg="#00FF00").pack(fill='x', pady=(10, 2))
            tk.Label(self.config_frame, text="Your Name:", bg=PANEL_BG, fg=TEXT,
                     font=('Segoe UI', 8)).pack(anchor='w', pady=(4, 2))
            self._entry(self.config_frame, self.player_name).pack(fill='x', pady=2, ipady=3)
            tk.Label(self.config_frame, text="Play as:", bg=PANEL_BG, fg=TEXT,
                     font=('Segoe UI', 8)).pack(anchor='w', pady=(8, 2))
            color_frame = tk.Frame(self.config_frame, bg=PANEL_BG); color_frame.pack(fill='x', pady=2)
            tk.Radiobutton(color_frame, text="⚪ White", variable=self.player_color, value="white",
                           bg=PANEL_BG, fg="#FFD700", selectcolor=BTN_BG,
                           font=('Segoe UI', 9, 'bold')).pack(side='left', padx=(0, 10))
            tk.Radiobutton(color_frame, text="⚫ Black", variable=self.player_color, value="black",
                           bg=PANEL_BG, fg="#C8C8C8", selectcolor=BTN_BG,
                           font=('Segoe UI', 9, 'bold')).pack(side='left')
            tk.Frame(self.config_frame, bg='#2a2a4a', height=1).pack(fill='x', pady=8)
            self._lbl(self.config_frame, "◈ OPPONENT ENGINE", 9, bold=True, fg=ACCENT).pack(fill='x', pady=(4, 2))
            rf = tk.Frame(self.config_frame, bg=PANEL_BG); rf.pack(fill='x', pady=2)
            self._entry(rf, self.e2_path).pack(side='left', fill='x', expand=True, ipady=4)
            self._btn(rf, "…", self._browse_opponent, small=True).pack(side='right', padx=(4, 0))
            self._entry(self.config_frame, self.e2_name, fg=ACCENT).pack(fill='x', pady=2, ipady=3)
            ef = tk.Frame(self.config_frame, bg=INFO_BG); ef.pack(fill='x', pady=2)
            self._lbl(ef, "Eval:", 8, bg=INFO_BG, fg="#888").pack(side='left', padx=4)
            tk.Label(ef, textvariable=self.e2_eval, bg=INFO_BG, fg="#7FFF00",
                     font=('Consolas', 8)).pack(side='left')
            self._lbl(ef, " D:", 8, bg=INFO_BG, fg="#888").pack(side='left')
            tk.Label(ef, textvariable=self.e2_depth, bg=INFO_BG, fg="#7FFF00",
                     font=('Consolas', 8)).pack(side='left')
            tk.Frame(self.config_frame, bg='#2a2a4a', height=1).pack(fill='x', pady=4)

    def _on_mode_change(self):
        self._build_config_ui()
        msg = ("Enter your name, choose color, and load an engine"
               if self.play_mode.get() == "human_vs_engine"
               else "Load two engine .exe files, then press ▶ Start")
        self._status(msg)

    def _browse_opponent(self):
        path = filedialog.askopenfilename(
            title="Select Opponent Engine",
            filetypes=[("Executables", "*.exe *.bin *"), ("All", "*.*")])
        if not path: return
        name = os.path.splitext(os.path.basename(path))[0]
        self.e2_path.set(path)
        self.e2_name.set(f"{name} (Engine)")

    # ── Center panel (board) ──────────────────────────────

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

        # Black banner
        self.black_banner = tk.Frame(p, bg="#1a1a2a",
            highlightthickness=1, highlightbackground="#444444")
        self.black_banner.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(0, 3))
        self._black_name_lbl = tk.Label(self.black_banner, textvariable=self.e1_name,
            bg="#1a1a2a", fg="#C8C8C8", font=('Segoe UI', 11, 'bold'),
            anchor='center', pady=6)
        self._black_name_lbl.pack(side='left', expand=True)
        self._black_rank_lbl = tk.Label(self.black_banner, text="",
            bg="#1a1a2a", fg="#C8C8C8", font=('Segoe UI', 9), anchor='e', padx=8)
        self._black_rank_lbl.pack(side='right')

        # Board row
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

        rf = tk.Frame(board_inner, bg=BG); rf.pack(side='left')
        self.rank_labels = []
        for i in range(8):
            l = tk.Label(rf, text="", bg=BG, fg="#777",
                         font=('Consolas', 9), width=2, anchor='e')
            l.pack(side='top', ipady=sz//2-7)
            self.rank_labels.append(l)

        bcol = tk.Frame(board_inner, bg=BG); bcol.pack(side='left')
        self.canvas = tk.Canvas(bcol, width=sz*8, height=sz*8, bg=BG, bd=0,
                                 highlightthickness=2, highlightcolor=ACCENT,
                                 highlightbackground='#333')
        self.canvas.pack()
        self.selected_square = None
        self.canvas.bind('<Button-1>', self._on_board_click)

        ff = tk.Frame(bcol, bg=BG); ff.pack(fill='x')
        self.file_labels = []
        for i in range(8):
            l = tk.Label(ff, text="", bg=BG, fg="#777",
                         font=('Consolas', 9), width=4, anchor='center')
            l.pack(side='left', ipadx=sz//2-8)
            self.file_labels.append(l)

        # White banner
        self.white_banner = tk.Frame(p, bg="#1c2a1c",
            highlightthickness=1, highlightbackground="#555500")
        self.white_banner.grid(row=4, column=0, columnspan=2, sticky='ew', pady=(3, 0))
        self._white_name_lbl = tk.Label(self.white_banner, textvariable=self.e2_name,
            bg="#1c2a1c", fg="#FFD700", font=('Segoe UI', 11, 'bold'),
            anchor='center', pady=6)
        self._white_name_lbl.pack(side='left', expand=True)
        self._white_rank_lbl = tk.Label(self.white_banner, text="",
            bg="#1c2a1c", fg="#FFD700", font=('Segoe UI', 9), anchor='e', padx=8)
        self._white_rank_lbl.pack(side='right')

        self.check_lbl = tk.Label(p, text="", bg=BG, fg=CHECK_SQ,
                                   font=('Segoe UI', 10, 'bold'), anchor='center')
        self.check_lbl.grid(row=5, column=0, columnspan=2, sticky='ew', pady=(4, 0))

        self.quality_lbl = tk.Label(p, text="", bg=BG, fg=TEXT,
                                     font=('Segoe UI', 13, 'bold'), anchor='center')
        self.quality_lbl.grid(row=6, column=0, columnspan=2, sticky='ew', pady=(2, 0))

        self._update_coords()
        self.root.after(100, self._draw_eval_bar, 0)

    # ── Right panel (log) ─────────────────────────────────

    def _build_right(self, p):
        tk.Label(p, text="GAME LOG", bg=PANEL_BG, fg=ACCENT,
                 font=('Segoe UI', 12, 'bold')).pack(pady=(16, 4))
        tk.Frame(p, bg=ACCENT, height=2).pack(fill='x', padx=10, pady=2)

        self._lbl(p, "Moves (SAN):", 9, bold=True).pack(fill='x', padx=10, pady=(8, 2))
        mf = tk.Frame(p, bg=LOG_BG, highlightthickness=1, highlightbackground='#333')
        mf.pack(fill='both', expand=True, padx=10, pady=(0, 4))
        self.move_text = scrolledtext.ScrolledText(
            mf, bg=LOG_BG, fg="#DDD", font=('Consolas', 9), state='disabled',
            relief='flat', padx=6, pady=6, insertbackground=TEXT,
            wrap='word', selectbackground=BTN_BG)
        self.move_text.pack(fill='both', expand=True)
        self.move_text.tag_config('num',     foreground="#555")
        self.move_text.tag_config('black',   foreground="#CCCCCC")
        self.move_text.tag_config('white',   foreground="#FFD700", font=('Consolas', 9, 'bold'))
        self.move_text.tag_config('chk',     foreground="#FF8800", font=('Consolas', 9, 'bold'))
        self.move_text.tag_config('result',  foreground=ACCENT,    font=('Consolas', 10, 'bold'))
        self.move_text.tag_config('opening', foreground="#00BFFF",  font=('Consolas', 9, 'italic'))

        tk.Frame(p, bg='#2a2a4a', height=1).pack(fill='x', padx=10, pady=2)
        self._lbl(p, "Engine Output:", 9, bold=True).pack(fill='x', padx=10, pady=(4, 2))
        ef = tk.Frame(p, bg=LOG_BG, highlightthickness=1, highlightbackground='#333')
        ef.pack(fill='both', expand=True, padx=10, pady=(0, 4))
        self.eng_log = scrolledtext.ScrolledText(
            ef, bg=LOG_BG, fg="#0FA", font=('Consolas', 8), state='disabled',
            relief='flat', padx=6, pady=6, insertbackground=TEXT,
            wrap='char', selectbackground=BTN_BG, height=7)
        self.eng_log.pack(fill='both', expand=True)
        self.eng_log.tag_config('W', foreground="#FFD700")
        self.eng_log.tag_config('B', foreground="#AAAAAA")
        self.eng_log.tag_config('E', foreground="#FF4444")

        self.info_lbl = tk.Label(p, text="", bg=PANEL_BG, fg="#666",
                                  font=('Segoe UI', 8), anchor='w',
                                  wraplength=255, justify='left')
        self.info_lbl.pack(fill='x', padx=10, pady=(2, 8))

    # ═══════════════════════════════════════════════════════
    #  Drawing
    # ═══════════════════════════════════════════════════════

    def _update_coords(self):
        ranks = list(range(8, 0, -1)) if not self.flipped else list(range(1, 9))
        files = list('abcdefgh')      if not self.flipped else list('hgfedcba')
        for i, l in enumerate(self.rank_labels): l.config(text=str(ranks[i]))
        for i, l in enumerate(self.file_labels): l.config(text=files[i])

    def _draw_board(self):
        self.canvas.delete('all')
        sz = self.sq_size
        chk_king = self.board.find_king(self.board.turn) if self.board.in_check() else None
        lm_from = lm_to = None
        if self.last_move and len(self.last_move) >= 4:
            lm_from = (8 - int(self.last_move[1]), ord(self.last_move[0]) - ord('a'))
            lm_to   = (8 - int(self.last_move[3]), ord(self.last_move[2]) - ord('a'))

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
                light = (row + col) % 2 == 0
                color = LIGHT_SQ if light else DARK_SQ
                if self.selected_square and (br, bc) == self.selected_square:
                    color = "#7FFF00"
                elif lm_from and (br, bc) == lm_from: color = LAST_FROM
                elif lm_to   and (br, bc) == lm_to:   color = LAST_TO
                if chk_king and (br, bc) == chk_king:  color = CHECK_SQ

                x1, y1 = col * sz, row * sz; x2, y2 = x1 + sz, y1 + sz
                self.canvas.create_rectangle(x1, y1, x2, y2, fill=color, outline='')
                pc = self.board.get(br, bc)
                if pc and pc != '.':
                    sym = UNICODE.get(pc, pc)
                    fg  = '#F5F5F5' if pc.isupper() else '#1A1A1A'
                    sh  = '#000000' if pc.isupper() else '#888888'
                    fsz = int(sz * 0.60); cx, cy = x1 + sz//2, y1 + sz//2
                    self.canvas.create_text(cx+1, cy+2, text=sym, font=('Segoe UI', fsz), fill=sh)
                    self.canvas.create_text(cx,   cy,   text=sym, font=('Segoe UI', fsz), fill=fg)
                if (br, bc) in legal_dests:
                    cx, cy = x1 + sz//2, y1 + sz//2
                    if pc and pc != '.':
                        self.canvas.create_oval(x1+3, y1+3, x2-3, y2-3,
                                                outline="#00CC44", width=3, fill='')
                    else:
                        r = sz // 6
                        self.canvas.create_oval(cx-r, cy-r, cx+r, cy+r,
                                                fill="#00CC44", outline='')

        self.canvas.create_rectangle(0, 0, sz*8, sz*8, outline='#555', width=1)
        if self.board.in_check():
            side = "White" if self.board.turn == 'w' else "Black"
            self.check_lbl.config(text=f"⚠  {side} is in CHECK!")
        else:
            self.check_lbl.config(text="")
        self._update_banners()

    # ── Banner updates ────────────────────────────────────

    def _update_banners(self):
        if self.board.turn == 'b':
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
        try:
            games_raw   = self.db.get_all_games_for_elo()
            elo_ratings = compute_elo_ratings(games_raw)
            sorted_engines = sorted(elo_ratings.items(), key=lambda x: x[1], reverse=True)
            rank_map = {name: i + 1 for i, (name, _) in enumerate(sorted_engines)}
            total    = len(sorted_engines)

            mode = self.play_mode.get()
            if mode == "human_vs_engine":
                if self.player_color.get() == "white":
                    white_raw, black_raw = self.player_name.get(), self.e2_name.get()
                else:
                    white_raw, black_raw = self.e2_name.get(), self.player_name.get()
            else:
                black_raw, white_raw = self.e1_name.get(), self.e2_name.get()

            for raw, lbl_widget, rank_widget in [
                (black_raw, self._black_name_lbl, self._black_rank_lbl),
                (white_raw, self._white_name_lbl, self._white_rank_lbl),
            ]:
                key  = normalize_engine_name(raw)
                elo  = elo_ratings.get(key)
                if elo is not None:
                    tier_lbl, tier_col = get_tier(elo)
                    rank = rank_map.get(key, "?")
                    rank_widget.config(
                        text=f"#{rank}/{total}  {tier_lbl}  •  {elo} Elo",
                        fg=tier_col)
                else:
                    rank_widget.config(text="Unranked", fg="#555")
        except Exception as e:
            print(f"[_refresh_banners] {e}")

    # ═══════════════════════════════════════════════════════
    #  Board click (Human vs Engine)
    # ═══════════════════════════════════════════════════════

    def _on_board_click(self, event):
        if self.play_mode.get() != "human_vs_engine": return
        if not self.game_running: return
        if self._engine_thinking: return

        sz  = self.sq_size
        col = event.x // sz
        row = event.y // sz
        if not (0 <= row < 8 and 0 <= col < 8): return

        br, bc = (7 - row, 7 - col) if self.flipped else (row, col)
        human_color = self.player_color.get()

        with self.board_lock:
            turn_ok = ((human_color == "white" and self.board.turn == 'w') or
                       (human_color == "black" and self.board.turn == 'b'))
            if not turn_ok: return
            piece_at_click = self.board.get(br, bc)

        is_own_piece = (
            piece_at_click and piece_at_click != '.' and
            ((human_color == "white" and piece_at_click.isupper()) or
             (human_color == "black" and piece_at_click.islower()))
        )

        if self.selected_square is None:
            if is_own_piece:
                self.selected_square = (br, bc); self._draw_board()
            return

        from_r, from_c = self.selected_square
        if (br, bc) == (from_r, from_c):
            self.selected_square = None; self._draw_board(); return
        if is_own_piece:
            self.selected_square = (br, bc); self._draw_board(); return

        legal_moves = self.board.legal_moves()
        matching    = [m for m in legal_moves
                       if m[0] == from_r and m[1] == from_c
                       and m[2] == br    and m[3] == bc]
        if not matching:
            self.selected_square = None; self._draw_board(); return

        self.selected_square = None; self._draw_board()

        if any(m[4] for m in matching):
            promo = ask_promotion(self.root, 'w' if human_color == 'white' else 'b').lower()
            move_tuple = next((m for m in matching if m[4] == promo), matching[0])
            uci = (f"{chr(ord('a')+from_c)}{8-from_r}"
                   f"{chr(ord('a')+bc)}{8-br}{move_tuple[4]}")
        else:
            uci = f"{chr(ord('a')+from_c)}{8-from_r}{chr(ord('a')+bc)}{8-br}"

        with self.board_lock:
            still_ok = ((human_color == "white" and self.board.turn == 'w') or
                        (human_color == "black" and self.board.turn == 'b'))
            if not still_ok: return
            moves_before  = self.board.uci_moves_str()
            was_white     = (self.board.turn == 'w')
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

        self._draw_board(); self._update_info(); self._refresh_opening()
        self.root.after(0, self._refresh_banners)
        self._trigger_quality_analysis(moves_before, moves_after, was_white, san)

        if human_color == "black":
            self._pending_b = (move_num, san)
        else:
            if self._pending_b:
                n, b_san = self._pending_b
                self._log_move(n, b_san, san); self._pending_b = None
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

    # ═══════════════════════════════════════════════════════
    #  Logging helpers
    # ═══════════════════════════════════════════════════════

    def _status(self, msg):
        self.status_lbl.config(text=msg)

    def _log_move(self, num, b_san, w_san=None):
        self.move_text.config(state='normal')
        lines = int(self.move_text.index('end-1c').split('.')[0])
        if lines > 500: self.move_text.delete('1.0', '100.0')
        self.move_text.insert('end', f"{num}.", 'num')
        tb = 'chk' if ('+' in b_san or '#' in b_san) else 'black'
        self.move_text.insert('end', f" {b_san} ", tb)
        if w_san:
            tw = 'chk' if ('+' in w_san or '#' in w_san) else 'white'
            self.move_text.insert('end', f"{w_san}  ", tw)
        self.move_text.see('end'); self.move_text.config(state='disabled')

    def _log_result(self, txt):
        self.move_text.config(state='normal')
        self.move_text.insert('end', f"\n{txt}\n", 'result')
        self.move_text.see('end'); self.move_text.config(state='disabled')

    def _log_eng(self, txt, side='W'):
        self.eng_log.config(state='normal')
        self.eng_log.insert('end', txt + '\n', side)
        lines = int(self.eng_log.index('end-1c').split('.')[0])
        if lines > 700: self.eng_log.delete('1.0', '150.0')
        self.eng_log.see('end'); self.eng_log.config(state='disabled')

    def _update_info(self):
        wm, bm = self.board.material()
        d = wm - bm
        self.mat_lbl.config(
            text="Equal" if d == 0 else (f"White +{d}" if d > 0 else f"Black +{-d}"))
        t = "Black" if self.board.turn == 'b' else "White"
        self.info_lbl.config(
            text=f"Move {self.board.fullmove} | {t} to move | "
                 f"50-move: {self.board.halfmove}/100 | "
                 f"Plies: {len(self.board.move_history)}")

    def _show_eval(self, engine, side):
        if not engine: return
        info = engine.last_info
        sc   = info.get('score')
        st   = info.get('score_type', 'cp')
        dp   = info.get('depth')
        if sc is None:
            ev = '—'
        elif st == 'mate':
            ev = f"M{sc}"
        else:
            cp = sc if side == 'w' else -sc
            ev = f"{cp/100:+.2f}"
        ds = str(dp) if dp else '—'
        if side == 'b':
            self.e1_eval.set(ev); self.e1_depth.set(ds)
        else:
            self.e2_eval.set(ev); self.e2_depth.set(ds)
        if sc is not None:
            cp_bar = (30000 if sc > 0 else -30000) if st == 'mate' else sc
            if side == 'b': cp_bar = -cp_bar
            self._eval_bar_cp = cp_bar
            self.root.after(0, self._draw_eval_bar, cp_bar)

    # ═══════════════════════════════════════════════════════
    #  Engine management
    # ═══════════════════════════════════════════════════════

    def _browse(self, which):
        path = filedialog.askopenfilename(
            title=f"Select Engine {which}",
            filetypes=[("Executables", "*.exe *.bin *"), ("All", "*.*")])
        if not path: return
        name = os.path.splitext(os.path.basename(path))[0]
        if which == 1:
            self.e1_path.set(path); self.e1_name.set(f"{name} (Black)")
        else:
            self.e2_path.set(path); self.e2_name.set(f"{name} (White)")

    def _load_engines(self):
        p1, p2 = self.e1_path.get().strip(), self.e2_path.get().strip()
        errs = []
        for path, name_var, n, tag in [
            (p1, self.e1_name, 1, 'B'), (p2, self.e2_name, 2, 'W')
        ]:
            try:
                self.root.after(0, self._status, f"Loading {name_var.get()}…")
                eng = UCIEngine(path, name_var.get())
                eng.start()
                if n == 1: self.engine1 = eng
                else:       self.engine2 = eng
                self.root.after(0, self._log_eng, f"✓ {name_var.get()} ready", tag)
            except Exception as e:
                errs.append(f"Engine {n}: {e}")
        if errs:
            msg = '\n'.join(errs)
            self.root.after(0, lambda: messagebox.showerror("Engine Error", msg))
            return False
        return True

    def _load_opponent_engine(self):
        path = self.e2_path.get().strip()
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
        try:  self._do_engine_move()
        finally: self._engine_thinking = False

    def _do_engine_move(self):
        while self.game_paused and self.game_running: time.sleep(0.1)
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
            res = '1-0' if self.player_color.get() == 'white' else '0-1'
            winner = self.player_name.get()
            self.root.after(0, lambda: self._end_game(res, f"{name}'s engine process died", winner))
            return

        with self.board_lock:
            if self.board.turn != engine_turn: return
            mvs = self.board.uci_moves_str()

        moves_before     = mvs
        was_white_moving = (engine_turn == 'w')

        def on_info(info):
            self.root.after(0, lambda: self._show_eval(engine, side))

        try:
            uci = engine.get_best_move(mvs, self.movetime.get(), on_info=on_info)
        except Exception as ex:
            self.root.after(0, self._log_eng, f"[ERR] {ex}", tag); uci = None

        if not self.game_running: return

        if not uci:
            res    = '1-0' if self.player_color.get() == 'white' else '0-1'
            winner = self.player_name.get()
            self.root.after(0, lambda: self._end_game(res, f"{name} returned no move", winner))
            return

        self.root.after(0, self._log_eng, f"[{tag}] bestmove {uci}", tag)

        with self.board_lock:
            if not self.game_running: return
            if self.board.turn != engine_turn: return
            try:
                san, cap = self.board.apply_uci(uci)
            except ValueError as ex:
                self.root.after(0, self._log_eng, f"[ILLEGAL] {ex}", 'E')
                res    = '1-0' if self.player_color.get() == 'white' else '0-1'
                winner = self.player_name.get()
                self.root.after(0, lambda: self._end_game(
                    res, f"Illegal move by {name}: {uci}", winner))
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
                    self._log_move(n, b_san, san); self._pending_b = None
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
        msg = (f"⚠ CHECK! {player_sym} Your turn — you must get out of check!"
               if in_check else f"{player_sym} Your turn — click a piece to move")
        self.root.after(0, self._status, msg)

    # ═══════════════════════════════════════════════════════
    #  Game control
    # ═══════════════════════════════════════════════════════

    def _start_game(self):
        if self.game_running:
            messagebox.showinfo("Running", "Stop the current game first."); return

        mode = self.play_mode.get()
        if mode == "human_vs_engine":
            if not self.player_name.get().strip():
                messagebox.showerror("Error", "Please enter your name."); return
            if not self.e2_path.get().strip():
                messagebox.showerror("Error", "Please select an opponent engine."); return
        else:
            if not self.e1_path.get().strip() or not self.e2_path.get().strip():
                messagebox.showerror("Error", "Please select both engines."); return

        for n, path in ([(2, self.e2_path.get().strip())] if mode == "human_vs_engine"
                         else [(1, self.e1_path.get().strip()), (2, self.e2_path.get().strip())]):
            if not os.path.isfile(path):
                messagebox.showerror("Error", f"Engine {n} not found:\n{path}"); return

        for w in (self.move_text, self.eng_log):
            w.config(state='normal'); w.delete('1.0', 'end'); w.config(state='disabled')

        self.board.reset(); self.last_move = None; self._pending_b = None
        self.selected_square  = None
        self._engine_thinking = False
        self._last_eval_cp    = None
        self._last_quality    = None
        self._move_qualities  = []
        self._eval_bar_cp     = 0
        self._reset_opening()
        self._draw_board(); self._update_info()
        self.root.after(200, self._refresh_banners)
        self.root.after(100, self._draw_eval_bar, 0)
        if hasattr(self, 'quality_lbl'): self.quality_lbl.config(text="")
        for v in (self.e1_eval, self.e2_eval, self.e1_depth, self.e2_depth): v.set('—')
        self.mat_lbl.config(text="=")
        self.game_date       = datetime.now().strftime("%Y.%m.%d")
        self.game_start_time = time.time()
        self._status("⏳ Loading engine(s)…")

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
                self.game_running = True; self.game_paused = False; self.game_result = '*'
                threading.Thread(target=self._game_loop, daemon=True).start()

        threading.Thread(target=_load_and_start, daemon=True).start()

    def _toggle_pause(self):
        if not self.game_running: return
        self.game_paused = not self.game_paused
        self._status("⏸ PAUSED" if self.game_paused else "▶ Resuming…")

    def _stop_game(self):
        if not self.game_running:
            self._status("⏹ No game running."); return

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
            self.game_paused = was_paused; return

        winner_name = white_name if result == "1-0" else (black_name if result == "0-1" else None)
        self.game_running     = False
        self.game_paused      = False
        self._engine_thinking = False
        threading.Thread(target=self._kill_engines, daemon=True).start()

        if self.board.move_history or result != '*':
            duration = int(time.time() - self.game_start_time) if hasattr(self, 'game_start_time') else 0
            pgn = build_pgn(white_name, black_name, self.board.move_history, result,
                            self.game_date or datetime.now().strftime("%Y.%m.%d"),
                            opening_name=self.current_opening_name)
            self.db.save_game(white_name, black_name, result, reason, pgn,
                              len(self.board.move_history), duration)
            self._log_result(f"{result}  —  {reason}")

        if result == '*':
            self._status("⏹ Game aborted — no result recorded")
        else:
            clean = normalize_engine_name(winner_name) if winner_name else None
            self._status(f"⏹ Stopped — {clean} wins ({result})" if clean
                         else f"⏹ Stopped — {result}  ({reason})")

        if result != '*':
            self.game_result = result
            self.root.after(100, lambda: self._show_game_over_dialog(result, reason, winner_name))

    def _new_game(self):
        self.game_running     = False
        self.game_paused      = False
        self._engine_thinking = False
        threading.Thread(target=self._kill_engines, daemon=True).start()
        self.board.reset(); self.last_move = None; self._pending_b = None
        self.selected_square  = None
        self._last_eval_cp    = None
        self._last_quality    = None
        self._move_qualities  = []
        self._eval_bar_cp     = 0
        self.board_lock       = threading.Lock()
        self._reset_opening()
        for w in (self.move_text, self.eng_log):
            w.config(state='normal'); w.delete('1.0', 'end'); w.config(state='disabled')
        self._draw_board(); self._update_info()
        self.root.after(100, self._draw_eval_bar, 0)
        if hasattr(self, 'quality_lbl'): self.quality_lbl.config(text="")
        self.check_lbl.config(text=""); self.mat_lbl.config(text="=")
        for v in (self.e1_eval, self.e2_eval, self.e1_depth, self.e2_depth): v.set('—')
        self._status("New game — load engines and press ▶ Start")

    def _flip_board(self):
        self.flipped = not self.flipped; self._update_coords(); self._draw_board()

    def _kill_engines(self):
        for e in (self.engine1, self.engine2):
            if e:
                try: e.stop()
                except: pass

    def _export_pgn(self):
        if not self.board.move_history:
            messagebox.showinfo("PGN", "No moves to export yet."); return
        pgn = build_pgn(self.e2_name.get(), self.e1_name.get(),
                        self.board.move_history, self.game_result or '*',
                        self.game_date or datetime.now().strftime("%Y.%m.%d"),
                        opening_name=self.current_opening_name)
        path = filedialog.asksaveasfilename(
            defaultextension=".pgn",
            filetypes=[("PGN", "*.pgn"), ("All", "*.*")], title="Save PGN")
        if path:
            with open(path, 'w') as f: f.write(pgn)
            messagebox.showinfo("Saved", f"PGN saved:\n{path}")

    # ── Game-over dialog ──────────────────────────────────

    def _show_game_over_dialog(self, result, reason, winner_name):
        dialog = tk.Toplevel(self.root)
        dialog.title("Game Over")
        dialog.configure(bg=BG)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.update_idletasks()
        w, h = 480, 660
        dialog.geometry(f'{w}x{h}+{(dialog.winfo_screenwidth()-w)//2}+{(dialog.winfo_screenheight()-h)//2}')

        main_frame = tk.Frame(dialog, bg=BG)
        main_frame.pack(fill='both', expand=True, padx=20, pady=20)

        is_draw = result == '1/2-1/2'
        if winner_name and not is_draw:
            icon, title_text, title_color = "🏆", "VICTORY!", ACCENT
        else:
            icon, title_text, title_color = "🤝", "DRAW", "#FFD700"
            winner_name = None

        tk.Label(main_frame, text=icon, bg=BG, font=('Segoe UI', 48)).pack(pady=(10, 5))
        tk.Label(main_frame, text=title_text, bg=BG, fg=title_color,
                 font=('Segoe UI', 24, 'bold')).pack()

        if winner_name:
            clean_name = normalize_engine_name(winner_name)
            games_raw  = self.db.get_all_games_for_elo()
            elo_ratings = compute_elo_ratings(games_raw)
            winner_elo  = elo_ratings.get(clean_name)
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
            for _, _, q in self._move_qualities: counts[q] = counts.get(q, 0) + 1
            summary = "  ".join(
                f"{q}: {n}" for q, n in sorted(
                    counts.items(),
                    key=lambda x: list(QUALITY_COLORS.keys()).index(x[0])
                    if x[0] in QUALITY_COLORS else 99)
                if q not in ("Good",))
            if summary:
                tk.Label(main_frame, text=f"Move quality: {summary}", bg=BG, fg="#AAA",
                         font=('Segoe UI', 9)).pack(pady=2)

        btn_frame = tk.Frame(dialog, bg=BG)
        btn_frame.pack(fill='x', padx=20, pady=(0, 20))
        for text, cmd, accent in [
            ("New Game",     lambda: [dialog.destroy(), self._new_game()],     True),
            ("🏆 Rankings",  lambda: [dialog.destroy(), self._show_rankings()], False),
            ("Export PGN",   lambda: [dialog.destroy(), self._export_pgn()],   False),
            ("Close",        dialog.destroy,                                    False),
        ]:
            bg_c = ACCENT if accent else BTN_BG
            btn = tk.Button(btn_frame, text=text, command=cmd, bg=bg_c, fg=TEXT,
                            activebackground=BTN_HOV, activeforeground='white',
                            relief='flat', font=('Segoe UI', 10, 'bold' if accent else 'normal'),
                            padx=14, pady=10, cursor='hand2', borderwidth=0)
            btn.pack(side='left', expand=True, fill='x', padx=4)
            btn.bind('<Enter>', lambda e, b=btn, bg=bg_c: b.config(bg=BTN_HOV))
            btn.bind('<Leave>', lambda e, b=btn, bg=bg_c: b.config(bg=bg_c))
        dialog.bind('<Escape>', lambda e: dialog.destroy())

    # ═══════════════════════════════════════════════════════
    #  Engine-vs-Engine game loop
    # ═══════════════════════════════════════════════════════

    def _game_loop(self):
        movetime = self.movetime.get()
        delay    = self.delay.get()
        while self.game_running:
            while self.game_paused and self.game_running: time.sleep(0.1)
            if not self.game_running: break

            over, result, reason, winner_color = self.board.game_result()
            if over:
                winner_name = (self.e2_name.get() if winner_color == 'white'
                               else (self.e1_name.get() if winner_color == 'black' else None))
                self._end_game(result, reason, winner_name); return

            is_b   = (self.board.turn == 'b')
            engine = self.engine1 if is_b else self.engine2
            name   = (self.e1_name if is_b else self.e2_name).get()
            side   = 'b' if is_b else 'w'
            tag    = 'B' if is_b else 'W'
            self.root.after(0, self._status, f"{'♚' if is_b else '♔'} {name} thinking…")

            if not engine or not engine.alive:
                wc = 'white' if is_b else 'black'
                wn = self.e2_name.get() if wc == 'white' else self.e1_name.get()
                self._end_game('0-1' if is_b else '1-0',
                               f"{name}'s engine process died", wn); return

            moves_before     = self.board.uci_moves_str()
            was_white_moving = not is_b

            def on_info(info, _side=side, _eng=engine):
                self.root.after(0, lambda: self._show_eval(_eng, _side))

            try:
                uci = engine.get_best_move(moves_before, movetime, on_info=on_info)
            except Exception as ex:
                self.root.after(0, self._log_eng, f"[ERR] {ex}", tag); uci = None

            if not self.game_running: break
            if not uci:
                wc = 'white' if is_b else 'black'
                wn = self.e2_name.get() if wc == 'white' else self.e1_name.get()
                self._end_game('0-1' if is_b else '1-0',
                               f"{name} returned no move", wn); return

            self.root.after(0, self._log_eng, f"[{tag}] bestmove {uci}", tag)
            try:
                san, cap = self.board.apply_uci(uci)
            except ValueError as ex:
                self.root.after(0, self._log_eng, f"[ILLEGAL] {ex}", 'E')
                wc = 'white' if is_b else 'black'
                wn = self.e2_name.get() if wc == 'white' else self.e1_name.get()
                self._end_game('0-1' if is_b else '1-0',
                               f"Illegal move by {name}: {uci}", wn); return

            moves_after = self.board.uci_moves_str()
            self.last_move = uci
            move_num = (len(self.board.move_history) + 1) // 2
            self.root.after(0, self._draw_board)
            self.root.after(0, self._update_info)
            self.root.after(0, self._refresh_opening)
            self.root.after(0, self._refresh_banners)
            self._trigger_quality_analysis(moves_before, moves_after, was_white_moving, san)

            if is_b:
                self._pending_b = (move_num, san)
            else:
                if self._pending_b:
                    n, b_san = self._pending_b
                    self.root.after(0, self._log_move, n, b_san, san)
                    self._pending_b = None

            time.sleep(max(0.05, delay))

        if self._pending_b:
            n, b_san = self._pending_b
            self.root.after(0, self._log_move, n, b_san, None)
            self._pending_b = None

    # ── Game end ──────────────────────────────────────────

    def _end_game(self, result, reason, winner_name=None):
        self.game_running     = False
        self.game_result      = result
        self._engine_thinking = False
        self._kill_engines()

        duration = int(time.time() - self.game_start_time) if hasattr(self, 'game_start_time') else 0

        mode = self.play_mode.get()
        if mode == "human_vs_engine":
            if self.player_color.get() == "white":
                white_name, black_name = self.player_name.get(), self.e2_name.get()
            else:
                white_name, black_name = self.e2_name.get(), self.player_name.get()
        else:
            white_name, black_name = self.e2_name.get(), self.e1_name.get()

        pgn = build_pgn(white_name, black_name, self.board.move_history, result,
                        self.game_date or datetime.now().strftime("%Y.%m.%d"),
                        opening_name=self.current_opening_name)
        self.db.save_game(white_name, black_name, result, reason, pgn,
                          len(self.board.move_history), duration)

        status_msg = (f"🏁 {normalize_engine_name(winner_name)} wins by {reason}"
                      if winner_name else f"🏁 {result} — {reason}")
        self.root.after(0, self._status, status_msg)
        self.root.after(0, self._log_result, f"{result}  —  {reason}")
        self.root.after(150, self._refresh_banners)
        self.root.after(0, lambda: self._show_game_over_dialog(result, reason, winner_name))