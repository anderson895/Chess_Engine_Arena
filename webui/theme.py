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

# ── Selectable piece designs (folder under assets/ → label) ──
PIECE_SETS = {
    "pieces":   "Classic",
    "pieces_1": "Golden Oak",
    "pieces_2": "Fantasy",
    "pieces_3": "Marble",
}
_piece_state = {"folder": "pieces"}


def piece_folder():
    return _piece_state["folder"]


def set_piece_folder(folder):
    if folder in PIECE_SETS:
        _piece_state["folder"] = folder


def piece_src(code):
    """URL of a piece sprite in the active design, e.g. piece_src('wK')."""
    return f"/assets/{piece_folder()}/{code}.png"


# ── Selectable board styles (key → label, light sq, dark sq) ─
BOARD_THEMES = {
    "walnut":  ("Walnut",  LIGHT_SQ,  DARK_SQ),      # original default
    "green":   ("Green",   "#EBECD0", "#739552"),
    "blue":    ("Blue",    "#DEE3E6", "#8CA2AD"),
    "slate":   ("Slate",   "#CACDD1", "#5F6B77"),
    "coral":   ("Coral",   "#F1E9DD", "#B37360"),
    "midnight": ("Midnight", "#7A8494", "#3D4757"),
}
_board_state = {"theme": "walnut"}


def board_theme():
    return _board_state["theme"]


def set_board_theme(key):
    if key in BOARD_THEMES:
        _board_state["theme"] = key


def board_colors():
    _, light, dark = BOARD_THEMES[_board_state["theme"]]
    return light, dark


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
    /* 100vh minus header, status/opening rows, both player banners and
       gaps — keeps board + both banners visible without scrolling */
    max-width: min(calc(100vh - 250px), 100%);
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

/* A maximized dialog already fills the screen, so the 92vh/95vw clamp above
   would shrink the card below the space Quasar gave it and force the whole
   panel to scroll. */
.q-dialog__inner--maximized .arena-panel {{
    max-width: 100% !important;
    max-height: 100% !important;
    border-radius: 0;
}}

/* A card whose last row is a pinned footer hands its bottom padding over to
   that footer. Keeping it here would leave a bare strip underneath the
   buttons for the scrolling content to show through, and a negative bottom
   margin can't close it — that only pulls later siblings up, it does not
   grow the element itself. */
.q-dialog .arena-panel:has(.dlg-foot) {{
    padding-bottom: 0;
}}

/* Footer button rows stay pinned and visible while the dialog scrolls. The
   side margins widen the row over the card's left/right padding, so the bar
   spans edge to edge. --nicegui-default-padding is what .nicegui-card
   actually uses, so this tracks it rather than hardcoding 16px. */
.q-dialog .arena-panel .dlg-foot {{
    --pad: var(--nicegui-default-padding, 1rem);
    position: sticky;
    bottom: -1px;
    z-index: 5;
    background: var(--panel);
    margin: auto calc(-1 * var(--pad)) 0;
    padding: 6px var(--pad) var(--pad);
    /* w-full would hold the row at the content width and leave the right
       padding bare; the extra 2x pad matches the negative margins. */
    width: calc(100% + 2 * var(--pad)) !important;
    border-radius: 0 0 8px 8px;
}}

/* The PGN box fills the space it is given and scrolls inside, instead of
   stretching the dialog to fit the whole game. */
.pgn-box {{
    display: flex;
    flex-direction: column;
}}
/* q-field__inner is display:block, so the control below it will not pick up
   the height unless this link in the chain becomes a flex column too. */
.pgn-box .q-field__inner {{
    display: flex;
    flex-direction: column;
    min-height: 0;
}}
.pgn-box .q-field__control {{
    flex: 1 1 auto;
    min-height: 0;
}}
.pgn-box .q-field__control-container {{
    height: 100%;
}}
.pgn-box textarea.q-field__native {{
    height: 100% !important;
    min-height: 0;
    resize: none;
    overflow: auto;
}}

/* Tables marked .dlg-table fill the dialog and scroll their own body, so the
   column labels stay put. The body has to be the scroll container: letting
   the panel scroll instead would need the rows unclipped to keep the sticky
   offset, and unclipped rows paint outside the table. min-height:0 is what
   lets a flex child shrink below its content height and actually scroll. */
.q-dialog .arena-panel .dlg-table {{
    display: flex;
    flex-direction: column;
    min-height: 0;
}}
.q-dialog .arena-panel .dlg-table .q-table__middle {{
    flex: 1 1 auto;
    min-height: 0;
    overflow: auto;
}}
.q-dialog .arena-panel .dlg-table thead tr th {{
    position: sticky;
    top: 0;
    z-index: 2;
    background: var(--log);
    border-bottom: 1px solid #333;
}}
"""


def apply_theme():
    """Apply the arena dark theme to the current page."""
    ui.dark_mode().enable()
    ui.colors(primary=ACCENT, secondary=BTN_BG, accent=ACCENT,
              dark=BG, positive=COLOR_GREEN, negative=COLOR_RED,
              warning=COLOR_ORANGE, info=COLOR_BLUE)
    ui.add_css(GLOBAL_CSS)
    light, dark = board_colors()
    ui.add_css(f":root {{ --light-sq: {light}; --dark-sq: {dark}; }}")
    ui.query("body").style(f"background: {BG}")


def push_board_colors():
    """Apply the active board style to the connected client immediately."""
    light, dark = board_colors()
    ui.run_javascript(
        f"document.documentElement.style.setProperty('--light-sq', '{light}');"
        f"document.documentElement.style.setProperty('--dark-sq', '{dark}');")
