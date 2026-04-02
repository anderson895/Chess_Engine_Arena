# ═══════════════════════════════════════════════════════════
#  ui/theme.py — Centralized theme, fonts, and style helpers
# ═══════════════════════════════════════════════════════════

import tkinter as tk
from tkinter import ttk

from core.constants import (
    BG, PANEL_BG, ACCENT, TEXT, BTN_BG, BTN_HOV,
    LOG_BG, INFO_BG, RANK_TIERS,
)

# ── Cross-platform font stacks ───────────────────────────
# Tkinter will fall back through the tuple if a font isn't available.
FONT_FAMILY = "Segoe UI"
FONT_MONO   = "Consolas"

# Sizes
FONT_TITLE   = (FONT_FAMILY, 13, "bold")
FONT_HEADING = (FONT_FAMILY, 11, "bold")
FONT_BODY    = (FONT_FAMILY, 10)
FONT_SMALL   = (FONT_FAMILY, 9)
FONT_TINY    = (FONT_FAMILY, 8)

FONT_MONO_SM = (FONT_MONO, 9)
FONT_MONO_XS = (FONT_MONO, 8)

# ── Separator colour ─────────────────────────────────────
SEP_COLOR = "#2a2a4a"


# ═══════════════════════════════════════════════════════════
#  Ttk Treeview styling
# ═══════════════════════════════════════════════════════════

def apply_tree_style():
    """Apply the dark theme to all ttk Treeview widgets."""
    style = ttk.Style()
    style.theme_use("clam")
    style.configure(
        "Treeview",
        background=LOG_BG,
        foreground=TEXT,
        fieldbackground=LOG_BG,
        borderwidth=0,
        rowheight=28,
    )
    style.configure(
        "Treeview.Heading",
        background=BTN_BG,
        foreground=TEXT,
        borderwidth=1,
        font=(FONT_FAMILY, 9, "bold"),
    )
    style.map("Treeview", background=[("selected", ACCENT)])
    style.map("Treeview.Heading", background=[("active", ACCENT)])


def apply_notebook_style():
    """Apply the dark theme to ttk Notebook tabs."""
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure(
        "TNotebook.Tab",
        background=BTN_BG,
        foreground=TEXT,
        padding=[14, 6],
        font=(FONT_FAMILY, 10, "bold"),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", ACCENT)],
        foreground=[("selected", "white")],
    )


def apply_progressbar_style():
    """Apply theme to ttk Progressbar."""
    style = ttk.Style()
    style.theme_use("clam")
    style.configure(
        "TProgressbar",
        troughcolor=LOG_BG,
        background=ACCENT,
        thickness=14,
    )


# ═══════════════════════════════════════════════════════════
#  Separator factory
# ═══════════════════════════════════════════════════════════

def separator(parent, pad_x=10, pad_y=6, color=None):
    """Create a thin horizontal separator line."""
    s = tk.Frame(parent, bg=color or SEP_COLOR, height=1)
    s.pack(fill="x", padx=pad_x, pady=pad_y)
    return s


def accent_line(parent, pad_x=10, pad_y=2):
    """Create a coloured accent divider."""
    s = tk.Frame(parent, bg=ACCENT, height=2)
    s.pack(fill="x", padx=pad_x, pady=pad_y)
    return s
