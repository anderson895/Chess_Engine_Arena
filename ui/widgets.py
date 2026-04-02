# ═══════════════════════════════════════════════════════════
#  ui/widgets.py — Reusable themed widget factories
# ═══════════════════════════════════════════════════════════

import tkinter as tk
from core.constants import (
    BG, PANEL_BG, ACCENT, TEXT, BTN_BG, BTN_HOV, LOG_BG,
)
from ui.theme import (
    FONT_FAMILY, FONT_MONO,
    FONT_BODY, FONT_SMALL, FONT_TINY, FONT_MONO_XS,
)


def label(parent, text, size=10, bold=False, fg=TEXT, bg=PANEL_BG, anchor="w"):
    """Standard themed label."""
    return tk.Label(
        parent,
        text=text,
        bg=bg,
        fg=fg,
        anchor=anchor,
        font=(FONT_FAMILY, size, "bold" if bold else "normal"),
    )


def heading(parent, text, fg=ACCENT, bg=PANEL_BG):
    """Section heading label."""
    return tk.Label(
        parent,
        text=text,
        bg=bg,
        fg=fg,
        font=(FONT_FAMILY, 9, "bold"),
    )


def button(parent, text, command, accent=False, small=False):
    """Themed flat button with hover effects."""
    bg_c = ACCENT if accent else BTN_BG
    btn = tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg_c,
        fg=TEXT,
        activebackground=BTN_HOV,
        activeforeground="white",
        relief="flat",
        font=(FONT_FAMILY, 8 if small else 10, "normal"),
        padx=4,
        pady=2 if small else 5,
        cursor="hand2",
        borderwidth=0,
    )
    btn.bind("<Enter>", lambda e: btn.config(bg=BTN_HOV))
    btn.bind("<Leave>", lambda e: btn.config(bg=bg_c))
    return btn


def toolbar_button(parent, text, command, accent=False):
    """Compact button for the top toolbar."""
    bg_c = ACCENT if accent else "#1E1E3A"
    hov = BTN_HOV if accent else "#2E2E5A"
    btn = tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg_c,
        fg=TEXT,
        activebackground=hov,
        activeforeground="white",
        relief="flat",
        font=(FONT_FAMILY, 9, "bold"),
        padx=12,
        pady=0,
        cursor="hand2",
        borderwidth=0,
        height=2,
    )
    btn.bind("<Enter>", lambda e: btn.config(bg=hov))
    btn.bind("<Leave>", lambda e: btn.config(bg=bg_c))
    return btn


def entry(parent, var, fg=TEXT, width=None):
    """Themed text entry field."""
    kw = dict(
        textvariable=var,
        bg=LOG_BG,
        fg=fg,
        insertbackground=TEXT,
        font=(FONT_MONO, 8),
        relief="flat",
        highlightthickness=1,
        highlightcolor=ACCENT,
        highlightbackground="#333",
    )
    if width:
        kw["width"] = width
    return tk.Entry(parent, **kw)
