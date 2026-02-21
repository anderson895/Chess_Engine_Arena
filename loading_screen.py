# ═══════════════════════════════════════════════════════════
#  loading_screen.py — Startup loading screen
# ═══════════════════════════════════════════════════════════

import os
import sys
import threading
import tkinter as tk
from tkinter import ttk

from constants import BG, PANEL_BG, ACCENT, TEXT, LOG_BG
from engine import AnalyzerEngine
from opening_book import OpeningBook


class LoadingScreen:
    """
    Displayed on startup while the opening book CSV and Stockfish
    analyzer engine are loaded in background threads.

    When both tasks finish, the screen is torn down and ChessGUI is
    instantiated in the same root window.
    """

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

    # ── UI ────────────────────────────────────────────────

    def _build(self):
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill='both', expand=True, padx=40, pady=30)

        tk.Label(outer, text="♟", bg=BG, fg=ACCENT,
                 font=('Segoe UI', 60)).pack(pady=(0, 2))
        tk.Label(outer, text="Chess Engine Arena", bg=BG, fg=TEXT,
                 font=('Segoe UI', 22, 'bold')).pack()
        tk.Frame(outer, bg=ACCENT, height=2).pack(fill='x', pady=(12, 20))

        for attr_bar, attr_lbl, icon in [
            ('_open_bar', '_open_lbl', '📖  Openings CSV'),
            ('_anal_bar', '_anal_lbl', '🔍  Analyzer Engine'),
        ]:
            row = tk.Frame(outer, bg=BG)
            row.pack(fill='x', pady=(0, 10))
            tk.Label(row, text=icon, bg=BG, fg="#AAA",
                     font=('Segoe UI', 10), width=20, anchor='w').pack(side='left')
            bar = ttk.Progressbar(row, maximum=100, length=200, mode='indeterminate')
            bar.pack(side='left', padx=(8, 8))
            lbl = tk.Label(row, text="Loading…", bg=BG, fg="#666",
                           font=('Consolas', 9), width=16, anchor='w')
            lbl.pack(side='left')
            setattr(self, attr_bar, bar)
            setattr(self, attr_lbl, lbl)

        self._status_var = tk.StringVar(value="Initialising…")
        tk.Label(outer, textvariable=self._status_var, bg=BG, fg="#555",
                 font=('Segoe UI', 9), anchor='center').pack(pady=(16, 0))

        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TProgressbar',
                        troughcolor=LOG_BG, background=ACCENT, thickness=14)

        self._open_bar.start(12)
        self._anal_bar.start(12)

    # ── Loading logic ─────────────────────────────────────

    def _start_loading(self):
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
        except NameError:
            script_dir = os.getcwd()
        cwd = os.getcwd()

        # Opening book candidates
        csv_candidates = []
        for base in [cwd, script_dir]:
            for sub in ["opening", "openings", ""]:
                for fname in ["openings_sheet.csv", "openings.csv"]:
                    p = (os.path.join(base, sub, fname) if sub
                         else os.path.join(base, fname))
                    csv_candidates.append(p)

        # Analyzer engine candidates
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
                        self._status_var.set(f"Openings: {os.path.basename(p)}"),
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
        found_path = next((p for p in candidates if os.path.isfile(p)), None)
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

        # Import here to avoid circular imports at module load time
        from gui import ChessGUI
        ChessGUI(
            self.root,
            preloaded_book          = self._opening_book,
            preloaded_book_path     = self._opening_path,
            preloaded_analyzer      = self._analyzer_eng,
            preloaded_analyzer_path = self._analyzer_path,
        )