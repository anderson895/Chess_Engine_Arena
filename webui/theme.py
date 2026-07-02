# ═══════════════════════════════════════════════════════════
#  webui/theme.py — Shared colors, CSS and Quasar dark theme
# ═══════════════════════════════════════════════════════════

from nicegui import ui

from core.constants import (
    BG, PANEL_BG, ACCENT, TEXT, BTN_BG, LOG_BG, INFO_BG,
    LIGHT_SQ, DARK_SQ, LAST_FROM, LAST_TO, CHECK_SQ,
)

# Semantic aliases used across the web UI
COLOR_MUTED   = "#8a8aa0"
COLOR_FAINT   = "#55556a"
COLOR_GOLD    = "#FFD700"
COLOR_SILVER  = "#C8C8C8"
COLOR_BLUE    = "#00BFFF"
COLOR_GREEN   = "#1BECA0"
COLOR_ORANGE  = "#FF8800"
COLOR_RED     = "#FF4444"

GLOBAL_CSS = f"""
:root {{
    --bg: {BG};
    --panel: {PANEL_BG};
    --accent: {ACCENT};
    --text: {TEXT};
    --btn: {BTN_BG};
    --log: {LOG_BG};
    --info: {INFO_BG};
    --light-sq: {LIGHT_SQ};
    --dark-sq: {DARK_SQ};
    --last-from: {LAST_FROM};
    --last-to: {LAST_TO};
    --check-sq: {CHECK_SQ};
}}
body {{
    background: var(--bg);
    color: var(--text);
}}
.arena-panel {{
    background: var(--panel);
    border: 1px solid #2a2a4a;
    border-radius: 8px;
}}
.arena-heading {{
    color: var(--accent);
    font-weight: 700;
    letter-spacing: 0.06em;
    font-size: 0.8rem;
}}
.arena-log {{
    background: var(--log);
    border: 1px solid #333;
    border-radius: 6px;
    font-family: Consolas, monospace;
    font-size: 0.8rem;
}}
.mono {{ font-family: Consolas, monospace; }}

/* ── Board ────────────────────────────────────────────── */
.board-grid {{
    display: grid;
    grid-template-columns: repeat(8, 1fr);
    grid-template-rows: repeat(8, 1fr);
    aspect-ratio: 1 / 1;
    width: 100%;
    max-width: min(78vh, 100%);
    margin: 0 auto;
    border: 2px solid #333;
    border-radius: 4px;
    user-select: none;
}}
.board-sq {{
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: clamp(18px, 5.2vmin, 52px);
    line-height: 1;
    cursor: pointer;
}}
.board-sq.light  {{ background: var(--light-sq); }}
.board-sq.dark   {{ background: var(--dark-sq); }}
.board-sq.sel    {{ background: #7FFF00 !important; }}
.board-sq.lfrom  {{ background: var(--last-from) !important; }}
.board-sq.lto    {{ background: var(--last-to) !important; }}
.board-sq.chk    {{ background: var(--check-sq) !important; }}
.board-sq.dot::after {{
    content: '';
    position: absolute;
    width: 26%;
    height: 26%;
    border-radius: 50%;
    background: #00CC44;
    opacity: 0.9;
}}
.board-sq.ring::after {{
    content: '';
    position: absolute;
    inset: 6%;
    border: 3px solid #00CC44;
    border-radius: 50%;
}}
.board-sq .coord {{
    position: absolute;
    font-size: clamp(8px, 1.3vmin, 13px);
    font-weight: 700;
    font-family: Consolas, monospace;
    pointer-events: none;
}}
.board-sq .coord.rank {{ top: 2px; left: 3px; }}
.board-sq .coord.file {{ bottom: 1px; right: 3px; }}
.board-sq.light .coord {{ color: var(--dark-sq); }}
.board-sq.dark  .coord {{ color: var(--light-sq); }}
.board-sq img.pc-img {{
    width: 88%;
    height: 88%;
    object-fit: contain;
    pointer-events: none;
    filter: drop-shadow(1px 2px 2px rgba(0,0,0,0.45));
}}

/* ── Header nav cards ─────────────────────────────────── */
img.nav-card {{
    height: 54px;
    width: auto;
    cursor: pointer;
    border-radius: 8px;
    transition: transform 0.12s ease, box-shadow 0.12s ease;
}}
img.nav-card:hover {{
    transform: translateY(-2px) scale(1.05);
    box-shadow: 0 4px 10px rgba(233, 69, 96, 0.35);
}}
img.btn-ic {{
    height: 16px;
    width: auto;
    pointer-events: none;
}}

/* ── Eval bar ─────────────────────────────────────────── */
.eval-bar {{
    width: 22px;
    background: #1A1A1A;
    border: 1px solid #555;
    border-radius: 3px;
    position: relative;
    overflow: hidden;
}}
.eval-bar .white-part {{
    position: absolute;
    bottom: 0;
    width: 100%;
    background: #F0F0F0;
    transition: height 0.4s ease;
}}
.eval-bar .mid {{
    position: absolute;
    top: 50%;
    width: 100%;
    border-top: 1px solid #666;
}}
.eval-bar .val {{
    position: absolute;
    width: 100%;
    text-align: center;
    font-family: Consolas, monospace;
    font-size: 9px;
    font-weight: 700;
    z-index: 2;
}}

/* ── Player banners ───────────────────────────────────── */
.player-banner {{
    border: 1px solid #444;
    border-radius: 6px;
    padding: 4px 12px;
    background: #1a1a2a;
    transition: border-color 0.2s, background 0.2s;
}}
.player-banner.active {{
    border: 2px solid var(--accent);
    background: #252538;
}}

/* Quasar dark tweaks */
.q-table {{ background: var(--log); color: var(--text); }}
.q-table th {{ color: var(--accent); font-weight: 700; }}

/* Every modal adapts to the window: clamp + scroll instead of overflow.
   flex-direction/nowrap are forced because Quasar's `.flex` class sets
   flex-wrap: wrap, which would wrap content into side-by-side columns
   once max-height kicks in (header/search left, table right). */
.q-dialog .arena-panel {{
    display: flex !important;
    flex-direction: column !important;
    flex-wrap: nowrap !important;
    max-width: 95vw !important;
    max-height: 92vh !important;
    overflow: auto;
}}

/* Footer button rows stay pinned and visible while the dialog scrolls */
.q-dialog .arena-panel .dlg-foot {{
    position: sticky;
    bottom: -1px;
    z-index: 5;
    background: var(--panel);
    margin-top: auto;
    padding-top: 6px;
}}
"""


def apply_theme():
    """Apply the arena dark theme to the current page."""
    ui.dark_mode().enable()
    ui.colors(primary=ACCENT, secondary=BTN_BG, accent=ACCENT,
              dark=BG, positive=COLOR_GREEN, negative=COLOR_RED,
              warning=COLOR_ORANGE, info=COLOR_BLUE)
    ui.add_css(GLOBAL_CSS)
    ui.query("body").style(f"background: {BG}")
